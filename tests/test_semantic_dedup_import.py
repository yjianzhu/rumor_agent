import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.analyzer.analyzer import hash_suffix, slugify
from src.config import settings
from src.db.crud import count_rumors, get_rumor_by_slug, get_rumor_by_slug_hash
from src.main import import_candidate_jsonl, import_jsonl_file

from tests.conftest import write_jsonl


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SAMPLE = ROOT / "examples" / "小米景明汽车谣言.jsonl"
CANDIDATE_SAMPLE = ROOT / "data" / "staging" / "candidates" / "candidate_20260506_002007.jsonl"


def _read_first_jsonl(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def _base_embedding() -> list[float]:
    vec = [0.0] * settings.EMBEDDING_DIM
    vec[0] = 1.0
    return vec


def _near_embedding() -> list[float]:
    vec = _base_embedding()
    vec[1] = 0.01
    return vec


@pytest.mark.parametrize(
    ("variant_title", "variant_content"),
    [
        (
            "小米景明子公司被质疑规避赔偿责任",
            "网上有人称小米汽车把销售和服务拆到景明等多家公司，是为了在诉讼中降低母公司赔偿责任。",
        ),
        (
            "小米汽车景明主体被指抬高维权门槛",
            "相关传言认为小米通过多个景明子公司分散合同主体，让消费者维权时面对更复杂的主体关系。",
        ),
        (
            "网传小米通过景明公司架构逃避连带责任",
            "社交平台讨论称小米景明及地方子公司构成主体迷宫，可借独立法人身份规避汽车业务纠纷。",
        ),
    ],
)
def test_jsonl_import_skips_similar_sample_texts(tmp_path, db, variant_title, variant_content):
    sample = _read_first_jsonl(EXAMPLE_SAMPLE)
    probe = uuid4().hex[:8]
    seed = {
        **sample,
        "title": f"{sample['title']} {probe}",
        "rumor_content": f"{sample['rumor_content']}\n样本编号：{probe}",
    }
    variant = {
        **sample,
        "title": f"{variant_title} {probe}",
        "rumor_content": f"{variant_content}\n样本编号：{probe}",
    }

    with patch("src.main._safe_get_embedding", return_value=_base_embedding()):
        seed_stats = import_jsonl_file(write_jsonl(tmp_path, [seed], filename="seed.jsonl"))

    assert seed_stats.succeeded == 1
    assert get_rumor_by_slug(db, slugify(seed["title"])) is not None
    before_count = count_rumors(db)

    with patch("src.main._safe_get_embedding", return_value=_near_embedding()):
        stats = import_jsonl_file(write_jsonl(tmp_path, [variant], filename="variant.jsonl"))

    assert stats.processed == 1
    assert stats.succeeded == 0
    assert stats.duplicates == 1
    assert stats.failed == 0
    assert count_rumors(db) == before_count
    assert get_rumor_by_slug(db, slugify(variant["title"])) is None


@pytest.mark.parametrize(
    ("variant_title", "variant_content"),
    [
        (
            "雷军直播使用苹果手机的说法再次引发争议",
            "有视频称雷军直播时疑似使用苹果设备，也有内容反驳其当时主要使用小米手机，争议集中在品牌一致性。",
        ),
        (
            "网传雷军直播露出竞品手机引发米粉讨论",
            "围绕雷军直播设备的讨论出现两种说法，一方质疑使用竞品，另一方认为截图和视频解读失真。",
        ),
    ],
)
def test_candidate_import_merges_similar_candidate_texts(tmp_path, db, variant_title, variant_content):
    sample = _read_first_jsonl(CANDIDATE_SAMPLE)
    probe = uuid4().hex[:8]
    seed_url = f"https://seed.example.com/{probe}"
    variant_url = f"https://variant.example.com/{probe}"
    seed = {
        **sample,
        "title": f"{sample['title']} {probe}",
        "content": f"{sample['content']}\n样本编号：{probe}",
        "source_urls": [seed_url],
        "keyword": f"seed-keyword-{probe}",
    }
    variant = {
        **sample,
        "title": f"{variant_title} {probe}",
        "content": f"{variant_content}\n样本编号：{probe}",
        "source_urls": [variant_url],
        "keyword": f"variant-keyword-{probe}",
    }

    with patch("src.main._safe_get_embedding", return_value=_base_embedding()):
        seed_stats = import_candidate_jsonl(write_jsonl(tmp_path, [seed], filename="seed-candidate.jsonl"))

    assert seed_stats.succeeded == 1
    before_count = count_rumors(db)

    with patch("src.main._safe_get_embedding", return_value=_near_embedding()):
        stats = import_candidate_jsonl(write_jsonl(tmp_path, [variant], filename="variant-candidate.jsonl"))

    assert stats.processed == 1
    assert stats.succeeded == 0
    assert stats.duplicates == 0
    assert stats.merged == 1
    assert stats.failed == 0
    assert count_rumors(db) == before_count

    seed_slug = slugify(seed["title"])
    rumor = get_rumor_by_slug_hash(db, hash_suffix(f"{seed['title']}\n{seed['content']}"))
    assert rumor is not None
    assert rumor.slug.startswith(seed_slug)
    assert seed_url in (rumor.source_urls or [])
    assert variant_url in (rumor.source_urls or [])
    assert seed["keyword"] in (rumor.tags or [])
    assert variant["keyword"] in (rumor.tags or [])
    assert rumor.merge_count == 1


# ─── Lower-level helpers (unit, no DB) ───────────────────────────────────────

class TestResolveSlug:
    def test_high_similarity_rejected(self):
        """When find_similar_rumor matches, _resolve_slug returns hit with existing rumor."""
        from src.main import _resolve_slug
        from unittest.mock import MagicMock

        vec = [1.0] * settings.EMBEDDING_DIM
        db = MagicMock()
        with patch("src.main.get_rumor_by_slug", return_value=None):
            similar_rumor = MagicMock()
            similar_rumor.slug = "existing-slug"
            with patch("src.main.find_similar_rumor", return_value=similar_rumor):
                result = _resolve_slug(db, "test-slug", "content", vec)
                assert result.slug is None
                assert result.existing is similar_rumor

    def test_low_similarity_passes(self):
        from src.main import _resolve_slug
        from unittest.mock import MagicMock

        vec = [1.0] * settings.EMBEDDING_DIM
        db = MagicMock()
        with patch("src.main.get_rumor_by_slug", return_value=None):
            with patch("src.main.find_similar_rumor", return_value=None):
                result = _resolve_slug(db, "test-slug", "content", vec)
                assert result.slug == "test-slug"
                assert result.existing is None

    def test_no_embedding_falls_back_to_hash(self):
        from src.main import _resolve_slug
        from unittest.mock import MagicMock

        db = MagicMock()
        with patch("src.main.get_rumor_by_slug", return_value=None):
            result = _resolve_slug(db, "test-slug", "content", None)
            assert result.slug == "test-slug"
            assert result.existing is None


class TestSafeGetEmbedding:
    def test_returns_none_on_failure(self):
        from src.main import _safe_get_embedding

        with patch("src.main.get_embedding", side_effect=RuntimeError("API down")):
            assert _safe_get_embedding("test text") is None
