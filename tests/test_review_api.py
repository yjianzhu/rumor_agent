"""Tests for the manual review PATCH endpoint."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.db.crud import create_rumor
from src.db.models import RumorStatus
from src.db.schemas import RumorCreate


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def seeded_rumor(db):
    """Insert one DUBIOUS rumor and return it."""
    slug = f"review-test-{uuid4().hex[:8]}"
    rumor = create_rumor(db, RumorCreate(
        title=slug,
        slug=slug,
        rumor_content="content needing human review",
        status=RumorStatus.DUBIOUS,
    ))
    db.commit()
    return rumor


class TestRumorReviewEndpoint:
    def test_full_review_payload_updates_all_fields(self, client, seeded_rumor):
        r = client.patch(f"/api/rumors/{seeded_rumor.slug}", json={
            "status": "FAKE",
            "truth_content": "Officials confirmed it is fabricated.",
            "is_published": True,
        })

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "FAKE"
        assert body["truth_content"] == "Officials confirmed it is fabricated."
        assert body["is_published"] is True

    def test_partial_update_preserves_other_fields(self, client, seeded_rumor):
        client.patch(f"/api/rumors/{seeded_rumor.slug}", json={
            "status": "FAKE",
            "truth_content": "verdict text",
        })
        r = client.patch(f"/api/rumors/{seeded_rumor.slug}", json={"is_published": True})

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "FAKE"
        assert body["truth_content"] == "verdict text"
        assert body["is_published"] is True

    def test_unknown_slug_returns_404(self, client):
        r = client.patch("/api/rumors/does-not-exist-xxx", json={"status": "FAKE"})
        assert r.status_code == 404

    def test_empty_body_rejected(self, client, seeded_rumor):
        r = client.patch(f"/api/rumors/{seeded_rumor.slug}", json={})
        assert r.status_code == 422

    def test_invalid_status_rejected(self, client, seeded_rumor):
        r = client.patch(f"/api/rumors/{seeded_rumor.slug}", json={"status": "BOGUS"})
        assert r.status_code == 422

    def test_content_fields_updated(self, client, seeded_rumor):
        r = client.patch(f"/api/rumors/{seeded_rumor.slug}", json={
            "title": "Corrected Title",
            "summary": "one-line summary",
            "rumor_content": "Cleaned-up rumor body.",
        })

        assert r.status_code == 200
        body = r.json()
        assert body["title"] == "Corrected Title"
        assert body["summary"] == "one-line summary"
        assert body["rumor_content"] == "Cleaned-up rumor body."
        # Verdict fields untouched
        assert body["status"] == "DUBIOUS"
        assert body["is_published"] is False

    def test_empty_title_rejected(self, client, seeded_rumor):
        r = client.patch(f"/api/rumors/{seeded_rumor.slug}", json={"title": ""})
        assert r.status_code == 422
