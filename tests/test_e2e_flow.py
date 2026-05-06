"""End-to-end flow: raw JSONL → triage → import-candidate → list/detail UI → review form.

Mocks the LLM and embedding layers; everything else is real (DB, FastAPI app, htmx
contracts). Verifies the full ingest-to-review loop the user wants to demo.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.ingest.triage import triage_raw_jsonl
from src.main import import_candidate_jsonl


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_full_pipeline_collect_to_review(client, db, tmp_path: Path):
    probe = f"e2e-{uuid4().hex[:6]}"
    keyword = f"keyword-{probe}"

    # ── Stage 1: synthetic raw JSONL (mimics what collect-bili would produce) ──
    raw_records = [
        {
            "keyword": keyword,
            "title": f"事件A标题足够长 {probe}",
            "description": "争议描述A：用户投诉产品质量，引发广泛讨论",
            "arcurl": "https://www.bilibili.com/video/AAAAA",
            "bvid": "AAAAA",
            "rank_meta": {"rank_offset": 0, "play": 5000, "like": 200, "danmaku": 30},
        },
        {
            "keyword": keyword,
            "title": f"事件B标题足够长 {probe}",
            "description": "争议描述B：营销宣传与实际不符",
            "arcurl": "https://www.bilibili.com/video/BBBBB",
            "bvid": "BBBBB",
            "rank_meta": {"rank_offset": 1, "play": 3000, "like": 150, "danmaku": 20},
        },
    ]
    raw_path = tmp_path / f"bili_{probe}.jsonl"
    with raw_path.open("w", encoding="utf-8") as f:
        for r in raw_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ── Stage 2: triage with mocked LLM ──
    mock_events = [
        {
            "title": f"产品质量争议 {probe}",
            "content": f"Bilibili用户称产品A质量存在问题，引发广泛讨论 [{probe}]",
            "source_urls": ["https://www.bilibili.com/video/AAAAA"],
            "controversy_type": "质量",
        },
        {
            "title": f"营销宣传争议 {probe}",
            "content": f"Bilibili用户指出宣传与实物不符 [{probe}]",
            "source_urls": ["https://www.bilibili.com/video/BBBBB"],
            "controversy_type": "营销宣传",
        },
    ]
    candidate_dir = tmp_path / "candidates"

    with patch("src.ingest.triage.llm_chat", return_value=json.dumps(mock_events)):
        candidate_path = triage_raw_jsonl([raw_path], candidate_dir=candidate_dir)

    assert candidate_path.exists()
    candidate_lines = candidate_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(candidate_lines) == 2

    # ── Stage 3: import-candidate (no embedding API hit during ingest) ──
    with patch("src.main._safe_get_embedding", return_value=None):
        stats = import_candidate_jsonl(candidate_path)
    assert stats.succeeded == 2
    assert stats.failed == 0
    assert stats.duplicates == 0

    # ── Stage 4: pending queue (default view) shows both new rumors ──
    r = client.get(f"/?tag={keyword}")
    assert r.status_code == 200
    html = r.text
    assert f"产品质量争议 {probe}" in html
    assert f"营销宣传争议 {probe}" in html
    # Pending tab should be active
    assert 'bg-indigo-600 text-white' in html

    # Stats partial works
    r_stats = client.get("/partials/stats")
    assert r_stats.status_code == 200

    # ── Stage 5: open detail page for first rumor ──
    from src.db.models import Rumor
    rumor = db.query(Rumor).filter(Rumor.title == f"产品质量争议 {probe}").one()
    slug = rumor.slug

    r_detail = client.get(f"/rumors/{slug}")
    assert r_detail.status_code == 200
    detail_html = r_detail.text
    assert 'id="rumor-article"' in detail_html
    assert 'name="status"' in detail_html
    # Initially DUBIOUS, not published
    assert "DUBIOUS" in detail_html
    assert "未发布" in detail_html

    # ── Stage 6: human review via form-friendly partial endpoint ──
    review_resp = client.post(
        f"/partials/rumors/{slug}/review",
        data={
            "status": "FAKE",
            "truth_content": f"经核查，{probe} 系不实信息。已联系平台标记。",
            "is_published": "1",
        },
    )
    assert review_resp.status_code == 200
    after_review = review_resp.text
    assert "FAKE" in after_review
    assert "已发布" in after_review
    assert f"经核查，{probe} 系不实信息" in after_review

    # ── Stage 7: now the rumor moved to "published" view ──
    r_pub = client.get(f"/?view=published&tag={keyword}")
    assert f"产品质量争议 {probe}" in r_pub.text

    r_pending = client.get(f"/?view=pending&tag={keyword}")
    assert f"产品质量争议 {probe}" not in r_pending.text  # no longer pending
    assert f"营销宣传争议 {probe}" in r_pending.text  # the other one still pending

    # ── Stage 8: API path also reflects the change ──
    r_api = client.get(f"/api/rumors/{slug}")
    assert r_api.status_code == 200
    body = r_api.json()
    assert body["status"] == "FAKE"
    assert body["is_published"] is True
    assert f"{probe} 系不实信息" in body["truth_content"]

    # ── Stage 9: PATCH JSON path can revert it ──
    r_patch = client.patch(f"/api/rumors/{slug}", json={"is_published": False})
    assert r_patch.status_code == 200
    assert r_patch.json()["is_published"] is False
