from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.app import app
from src.db.crud import create_analysis_result, create_rumor
from src.db.models import RumorStatus
from src.db.schemas import AnalysisResultCreate, MediaItem, RumorCreate


def test_public_detail_hides_summary_when_same_as_rumor_content(db):
    client = TestClient(app)
    slug = f"public-detail-{uuid4().hex[:8]}"
    content = "同一段传言正文"
    create_rumor(db, RumorCreate(
        title="公开详情去重测试",
        slug=slug,
        summary=content,
        rumor_content=content,
        status=RumorStatus.DUBIOUS,
        is_published=True,
    ))
    db.commit()

    response = client.get(f"/rumors/{slug}")

    assert response.status_code == 200
    assert "传言内容" in response.text
    assert response.text.count(content) == 1


def test_public_detail_keeps_distinct_summary(db):
    client = TestClient(app)
    slug = f"public-detail-{uuid4().hex[:8]}"
    create_rumor(db, RumorCreate(
        title="公开详情摘要测试",
        slug=slug,
        summary="这是独立摘要",
        rumor_content="这是传言正文",
        status=RumorStatus.DUBIOUS,
        is_published=True,
    ))
    db.commit()

    response = client.get(f"/rumors/{slug}")

    assert response.status_code == 200
    assert "这是独立摘要" in response.text
    assert "这是传言正文" in response.text


def test_public_detail_groups_rumor_and_debunk_images(db):
    client = TestClient(app)
    slug = f"public-detail-{uuid4().hex[:8]}"
    create_rumor(db, RumorCreate(
        title="公开详情图片分组测试",
        slug=slug,
        rumor_content="传言正文",
        truth_content="辟谣正文",
        status=RumorStatus.FAKE,
        is_published=True,
        media_files=[
            MediaItem(type="image", path=f"{slug}/rumor.jpg", label="rumor", caption="网传截图"),
            MediaItem(type="image", path=f"{slug}/debunk.jpg", label="debunk", caption="辟谣截图"),
        ],
    ))
    db.commit()

    response = client.get(f"/rumors/{slug}")

    assert response.status_code == 200
    assert "传言图片" in response.text
    assert "辟谣图片" in response.text
    assert response.text.index("事实核查") < response.text.index("传言图片")
    assert "网传截图" in response.text
    assert "辟谣截图" in response.text


def test_public_detail_does_not_show_analysis_evidence(db):
    client = TestClient(app)
    slug = f"public-detail-{uuid4().hex[:8]}"
    rumor = create_rumor(db, RumorCreate(
        title="公开详情分析信息隐藏测试",
        slug=slug,
        rumor_content="传言正文",
        truth_content="辟谣正文",
        status=RumorStatus.FAKE,
        is_published=True,
    ))
    create_analysis_result(db, AnalysisResultCreate(
        rumor_id=rumor.id,
        summary="analysis summary",
        truthfulness_score=0.1,
        evidence="不应在前台展示的核查依据",
        model_name="gpt-5.4",
    ))
    db.commit()

    response = client.get(f"/rumors/{slug}")

    assert response.status_code == 200
    assert "核查依据" not in response.text
    assert "不应在前台展示的核查依据" not in response.text
    assert "gpt-5.4" not in response.text
