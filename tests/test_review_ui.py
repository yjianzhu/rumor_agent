"""Tests for review-form partial route and view filtering."""
from __future__ import annotations

from uuid import uuid4
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops
from sqlalchemy import inspect
from sqlalchemy.orm.attributes import NO_VALUE

from src.api.app import app
from src.db.crud import create_analysis_result, create_rumor, get_rumor_by_slug, list_rumors
from src.db.models import RumorStatus
from src.db.schemas import AnalysisResultCreate, RumorCreate


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def dubious_rumor(db):
    slug = f"review-ui-{uuid4().hex[:8]}"
    rumor = create_rumor(db, RumorCreate(
        title=slug,
        slug=slug,
        rumor_content="content needing review",
        status=RumorStatus.DUBIOUS,
        tags=["__viewprobe__"],
    ))
    db.commit()
    return rumor


class TestReviewFormPartial:
    def test_form_submit_updates_rumor_and_returns_partial(self, client, dubious_rumor):
        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/review",
            data={
                "title": dubious_rumor.title,
                "status": "FAKE",
                "truth_content": "Officials confirmed it is fabricated.",
                "is_published": "1",
            },
        )
        assert r.status_code == 200
        html = r.text
        # Returned partial reflects updated values
        assert 'id="rumor-article"' in html
        assert "FAKE" in html
        assert "Officials confirmed it is fabricated." in html
        assert "已发布" in html

    def test_unchecked_is_published_treated_as_false(self, client, dubious_rumor):
        # First publish
        client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/review",
            data={
                "title": dubious_rumor.title,
                "status": "FAKE",
                "truth_content": "x",
                "is_published": "1",
            },
        )
        # Then submit without is_published checkbox (form omits unchecked boxes)
        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/review",
            data={
                "title": dubious_rumor.title,
                "status": "FAKE",
                "truth_content": "x",
            },
        )
        assert r.status_code == 200
        assert "未发布" in r.text

    def test_unknown_slug_returns_404(self, client):
        r = client.post(
            "/admin/partials/rumors/no-such-slug/review",
            data={"title": "anything", "status": "FAKE"},
        )
        assert r.status_code == 404

    def test_invalid_status_rejected(self, client, dubious_rumor):
        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/review",
            data={"title": dubious_rumor.title, "status": "BOGUS"},
        )
        # FastAPI Form validation does not enforce enum, but RumorStatus(...) raises ValueError →
        # caught as 500 unless we wrap. We accept 500/422 either way: reject.
        assert r.status_code >= 400

    def test_get_detail_partial_returns_form(self, client, dubious_rumor):
        r = client.get(f"/admin/partials/rumors/{dubious_rumor.slug}")
        assert r.status_code == 200
        html = r.text
        assert 'id="rumor-article"' in html
        assert 'name="title"' in html
        assert 'name="summary"' in html
        assert 'name="rumor_content"' in html
        assert 'name="status"' in html
        assert 'name="truth_content"' in html
        assert 'name="is_published"' in html

    def test_form_submit_updates_content_fields(self, client, dubious_rumor):
        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/review",
            data={
                "title": "Title After Edit",
                "summary": "edited summary line",
                "rumor_content": "Edited rumor body.",
                "status": "DUBIOUS",
            },
        )
        assert r.status_code == 200
        html = r.text
        assert "Title After Edit" in html
        assert "edited summary line" in html
        assert "Edited rumor body." in html

    def test_form_blank_title_rejected(self, client, dubious_rumor):
        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/review",
            data={"title": "   ", "status": "DUBIOUS"},
        )
        assert r.status_code == 400

    def test_media_upload_stores_selected_label(self, client, dubious_rumor, db, tmp_path, monkeypatch):
        from src.media import settings as media_settings

        monkeypatch.setattr(media_settings, "MEDIA_DIR", str(tmp_path))
        image = BytesIO()
        Image.new("RGB", (1, 1), color="white").save(image, format="PNG")
        original_bytes = image.getvalue()
        image.seek(0)

        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/media",
            data={"label": "debunk", "caption": "辟谣截图"},
            files=[("files", ("proof.png", image, "image/png"))],
        )

        assert r.status_code == 200
        assert "辟谣" in r.text
        loaded = get_rumor_by_slug(db, dubious_rumor.slug)
        assert loaded.media_files[0]["label"] == "debunk"
        assert loaded.media_files[0]["caption"] == "辟谣截图"
        assert (tmp_path / loaded.media_files[0]["path"]).read_bytes() == original_bytes

    def test_media_upload_stamps_rumor_image(self, client, dubious_rumor, db, tmp_path, monkeypatch):
        from src.media import settings as media_settings

        monkeypatch.setattr(media_settings, "MEDIA_DIR", str(tmp_path))
        image = BytesIO()
        Image.new("RGB", (300, 220), color="white").save(image, format="PNG")
        original_bytes = image.getvalue()
        image.seek(0)

        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/media",
            data={"label": "rumor", "caption": "网传截图"},
            files=[("files", ("claim.png", image, "image/png"))],
        )

        assert r.status_code == 200
        loaded = get_rumor_by_slug(db, dubious_rumor.slug)
        assert loaded.media_files[0]["label"] == "rumor"
        saved = (tmp_path / loaded.media_files[0]["path"]).read_bytes()
        assert saved != original_bytes
        original = Image.open(BytesIO(original_bytes)).convert("RGB")
        stamped = Image.open(BytesIO(saved)).convert("RGB")
        assert ImageChops.difference(original, stamped).getbbox() is not None

    def test_media_upload_rejects_rumor_gif(self, client, dubious_rumor, db, tmp_path, monkeypatch):
        from src.media import settings as media_settings

        monkeypatch.setattr(media_settings, "MEDIA_DIR", str(tmp_path))
        image = BytesIO()
        Image.new("RGB", (16, 16), color="white").save(image, format="GIF")
        image.seek(0)

        r = client.post(
            f"/admin/partials/rumors/{dubious_rumor.slug}/media",
            data={"label": "rumor"},
            files=[("files", ("claim.gif", image, "image/gif"))],
        )

        assert r.status_code == 200
        assert "谣言 GIF 暂不支持自动盖章" in r.text
        loaded = get_rumor_by_slug(db, dubious_rumor.slug)
        assert loaded.media_files == []

    def test_delete_rumor_returns_redirect_and_removes_record(self, client, dubious_rumor, db):
        slug = dubious_rumor.slug
        r = client.delete(f"/admin/partials/rumors/{slug}")

        assert r.status_code == 204
        assert r.headers.get("HX-Redirect") == "/admin"
        db.expire_all()
        assert get_rumor_by_slug(db, slug) is None

    def test_delete_unknown_slug_returns_404(self, client):
        r = client.delete("/admin/partials/rumors/no-such-slug")
        assert r.status_code == 404

    def test_delete_rumor_cascades_analysis(self, client, dubious_rumor, db):
        from src.db.models import AnalysisResult

        create_analysis_result(db, AnalysisResultCreate(
            rumor_id=dubious_rumor.id,
            model_name="test-model",
            evidence="e1",
            truthfulness_score=0.5,
        ))
        db.commit()
        rumor_id = dubious_rumor.id
        slug = dubious_rumor.slug

        r = client.delete(f"/admin/partials/rumors/{slug}")
        assert r.status_code == 204

        db.expire_all()
        assert get_rumor_by_slug(db, slug) is None
        leftover = db.query(AnalysisResult).filter_by(rumor_id=rumor_id).first()
        assert leftover is None


class TestViewFilter:
    def test_default_view_is_pending_excludes_published(self, client, db):
        slug_pending = f"vf-pending-{uuid4().hex[:6]}"
        slug_published = f"vf-published-{uuid4().hex[:6]}"
        create_rumor(db, RumorCreate(
            title=slug_pending, slug=slug_pending, rumor_content="p1",
            status=RumorStatus.DUBIOUS, is_published=False,
            tags=["__viewprobe__"],
        ))
        create_rumor(db, RumorCreate(
            title=slug_published, slug=slug_published, rumor_content="p2",
            status=RumorStatus.FAKE, is_published=True,
            tags=["__viewprobe__"],
        ))
        db.commit()

        r = client.get("/admin?tag=__viewprobe__")  # default view=pending
        assert r.status_code == 200
        assert slug_pending in r.text
        assert slug_published not in r.text

    def test_view_published_shows_only_published(self, client, db):
        slug_pending = f"vf-pending-{uuid4().hex[:6]}"
        slug_published = f"vf-published-{uuid4().hex[:6]}"
        create_rumor(db, RumorCreate(
            title=slug_pending, slug=slug_pending, rumor_content="p1",
            status=RumorStatus.DUBIOUS, is_published=False,
            tags=["__viewprobe__"],
        ))
        create_rumor(db, RumorCreate(
            title=slug_published, slug=slug_published, rumor_content="p2",
            status=RumorStatus.FAKE, is_published=True,
            tags=["__viewprobe__"],
        ))
        db.commit()

        r = client.get("/admin?view=published&tag=__viewprobe__")
        assert r.status_code == 200
        assert slug_published in r.text
        assert slug_pending not in r.text

    def test_view_all_shows_both(self, client, db):
        slug_pending = f"vf-pending-{uuid4().hex[:6]}"
        slug_published = f"vf-published-{uuid4().hex[:6]}"
        create_rumor(db, RumorCreate(
            title=slug_pending, slug=slug_pending, rumor_content="p1",
            status=RumorStatus.DUBIOUS, is_published=False,
            tags=["__viewprobe__"],
        ))
        create_rumor(db, RumorCreate(
            title=slug_published, slug=slug_published, rumor_content="p2",
            status=RumorStatus.FAKE, is_published=True,
            tags=["__viewprobe__"],
        ))
        db.commit()

        r = client.get("/admin?view=all&tag=__viewprobe__")
        assert r.status_code == 200
        assert slug_pending in r.text
        assert slug_published in r.text

    def test_invalid_view_falls_back_to_pending(self, client, dubious_rumor):
        r = client.get("/admin?view=garbage&tag=__viewprobe__")
        assert r.status_code == 200
        # Active tab should be 'pending'
        assert 'href="/admin?view=pending' in r.text
        # The pending tab link itself reads as the active state when view=pending
        assert dubious_rumor.slug in r.text  # dubious_rumor is unpublished, included


class TestListRumorsLoading:
    def test_include_analysis_eager_loads_card_analysis(self, db):
        slug = f"analysis-load-{uuid4().hex[:8]}"
        rumor = create_rumor(db, RumorCreate(
            title=slug,
            slug=slug,
            rumor_content="content",
            tags=["__analysisprobe__"],
        ))
        create_analysis_result(db, AnalysisResultCreate(
            rumor_id=rumor.id,
            summary="analysis summary",
            truthfulness_score=0.5,
        ))
        db.commit()
        db.expire_all()

        rows = list_rumors(db, tag="__analysisprobe__", include_analysis=True)
        loaded = next(r for r in rows if r.slug == slug)

        assert inspect(loaded).attrs.analysis.loaded_value is not NO_VALUE
        assert loaded.analysis.summary == "analysis summary"
