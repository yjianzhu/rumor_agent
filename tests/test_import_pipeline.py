import io
import json
from uuid import uuid4

import pytest

from src.analyzer.analyzer import hash_suffix, normalize_structured_analysis, slugify
from src.db.crud import get_analysis_by_rumor_id, get_rumor_by_slug
from src.db.models import RumorStatus
from src.db.schemas import _RumorSampleIn, MediaItem, StructuredRumorAnalysis
from src.main import import_jsonl_file, import_md_file

from tests.conftest import FakeAnalyzer, write_jsonl, write_md


# ─── JSONL direct import (unit, no DB) ───────────────────────────────────────

def test_jsonl_invalid_json_counted_as_failure(tmp_path, caplog):
    import logging
    path = write_jsonl(tmp_path, [
        {"title": "Valid rumor", "rumor_content": "content here"},
        '{"title": ',  # broken JSON
    ])
    with caplog.at_level(logging.ERROR):
        stats = import_jsonl_file(path, dry_run=True)

    assert stats.processed == 2
    assert stats.succeeded == 1
    assert stats.failed == 1
    assert "Line 2" in caplog.text


def test_jsonl_missing_title_counted_as_failure(tmp_path, caplog):
    import logging
    path = write_jsonl(tmp_path, [{"rumor_content": "no title here"}])
    with caplog.at_level(logging.ERROR):
        stats = import_jsonl_file(path, dry_run=True)

    assert stats.failed == 1


def test_jsonl_dry_run_preview_contains_slug(tmp_path):
    row = {"title": "Test Rumor Title", "rumor_content": "Some content", "status": "FAKE"}
    path = write_jsonl(tmp_path, [row])
    output = io.StringIO()

    stats = import_jsonl_file(path, dry_run=True, output=output)

    assert stats.succeeded == 1
    out = output.getvalue()
    assert "test-rumor-title" in out  # auto-generated slug


def test_jsonl_dry_run_includes_analysis_when_score_present(tmp_path):
    row = {
        "title": "Rumor with analysis",
        "rumor_content": "content",
        "truthfulness_score": 0.1,
        "evidence": "Some evidence",
    }
    path = write_jsonl(tmp_path, [row])
    output = io.StringIO()

    stats = import_jsonl_file(path, dry_run=True, output=output)

    assert stats.succeeded == 1
    assert "truthfulness_score" in output.getvalue()


def test_jsonl_explicit_slug_preserved(tmp_path):
    row = {"title": "Some Title", "slug": "my-custom-slug", "rumor_content": "content"}
    path = write_jsonl(tmp_path, [row])
    output = io.StringIO()

    stats = import_jsonl_file(path, dry_run=True, output=output)

    assert stats.succeeded == 1
    assert "my-custom-slug" in output.getvalue()


def test_jsonl_limit_respected(tmp_path):
    rows = [{"title": f"Rumor {i}", "rumor_content": "content"} for i in range(5)]
    path = write_jsonl(tmp_path, rows)

    stats = import_jsonl_file(path, dry_run=True, limit=3)

    assert stats.processed == 3


def test_jsonl_media_files_round_trip(tmp_path):
    row = {
        "title": "Rumor with images",
        "rumor_content": "content",
        "media_files": [
            {"type": "image", "path": "media/test/rumor.jpg", "label": "rumor"},
            {"type": "video", "path": "https://example.com/v.mp4", "label": "source", "caption": "vid"},
        ],
    }
    path = write_jsonl(tmp_path, [row])
    output = io.StringIO()

    stats = import_jsonl_file(path, dry_run=True, output=output)

    assert stats.succeeded == 1
    preview = json.loads(output.getvalue().split(": ", 1)[1])
    media = preview["rumor"]["media_files"]
    assert len(media) == 2
    assert media[0]["type"] == "image"
    assert media[1]["type"] == "video"
    assert media[1]["caption"] == "vid"


def test_jsonl_media_files_invalid_type_rejected(tmp_path, caplog):
    import logging
    row = {
        "title": "Bad media",
        "rumor_content": "content",
        "media_files": [{"type": "audio", "path": "media/x.mp3"}],
    }
    path = write_jsonl(tmp_path, [row])
    with caplog.at_level(logging.ERROR):
        stats = import_jsonl_file(path, dry_run=True)
    assert stats.failed == 1


# ─── Markdown import via LLM (unit, no DB) ───────────────────────────────────

def test_md_dry_run_calls_llm_and_prints_preview(tmp_path):
    md = write_md(tmp_path, "This is clearly a fake rumor debunked by officials.")
    response = StructuredRumorAnalysis(
        title="Fake Rumor",
        summary="Summary",
        rumor_content="content",
        truth_content="truth",
        status=RumorStatus.FAKE,
        tags=["test"],
        source_urls=None,
        analysis_summary="Analysis",
        truthfulness_score=0.1,
        evidence="Officials debunked it.",
    )
    output = io.StringIO()

    stats = import_md_file(md, dry_run=True, output=output, analyzer=FakeAnalyzer([response]))

    assert stats.succeeded == 1
    assert stats.failed == 0
    out = output.getvalue()
    assert "truthfulness_score" in out
    assert "FAKE" in out
    assert "Officials debunked it." in out


def test_md_llm_failure_counted_as_failed(tmp_path, caplog):
    import logging
    md = write_md(tmp_path, "Some markdown content.")

    with caplog.at_level(logging.ERROR):
        stats = import_md_file(md, dry_run=True, analyzer=FakeAnalyzer([RuntimeError("LLM down")]))

    assert stats.failed == 1
    assert "LLM down" in caplog.text


def test_no_verdict_signal_forces_dubious():
    sample = _RumorSampleIn(raw_text="This is only an unverified retelling of a claim.")
    analysis = StructuredRumorAnalysis(
        title="Title", summary=None, rumor_content="ignored", truth_content=None,
        status=RumorStatus.TRUE, tags=None, source_urls=None,
        analysis_summary=None, truthfulness_score=0.7, evidence="Model overreached",
    )
    normalized = normalize_structured_analysis(sample, analysis)
    assert normalized.status == RumorStatus.DUBIOUS


# ─── Database integration tests ──────────────────────────────────────────────

def test_jsonl_direct_import_creates_rumor_in_db(tmp_path, db):
    title = f"direct-import-{uuid4().hex[:8]}"
    path = write_jsonl(tmp_path, [{"title": title, "rumor_content": "content", "status": "FAKE"}])

    stats = import_jsonl_file(path)

    assert stats.succeeded == 1
    rumor = get_rumor_by_slug(db, slugify(title))
    assert rumor is not None
    assert rumor.status.value == "FAKE"


def test_jsonl_direct_import_with_analysis(tmp_path, db):
    title = f"direct-with-analysis-{uuid4().hex[:8]}"
    path = write_jsonl(tmp_path, [{
        "title": title,
        "rumor_content": "content",
        "status": "FAKE",
        "truthfulness_score": 0.05,
        "analysis_summary": "Clearly fake",
        "evidence": "Proof here",
    }])

    stats = import_jsonl_file(path)

    assert stats.succeeded == 1
    rumor = get_rumor_by_slug(db, slugify(title))
    assert rumor is not None
    analysis = get_analysis_by_rumor_id(db, rumor.id)
    assert analysis is not None
    assert analysis.summary == "Clearly fake"
    assert analysis.truthfulness_score == pytest.approx(0.05)


def test_jsonl_duplicate_slug_skipped(tmp_path, db):
    title = f"dup-slug-test-{uuid4().hex[:8]}"
    base_slug = slugify(title)
    path = write_jsonl(tmp_path, [
        {"title": title, "rumor_content": "first"},
        {"title": title, "slug": base_slug, "rumor_content": "second"},
    ])

    stats = import_jsonl_file(path)

    # same title but different content → both succeed (hash suffix differs)
    assert stats.succeeded == 2
    assert stats.duplicates == 0
    rumor = get_rumor_by_slug(db, base_slug)
    assert rumor is not None


def test_md_import_creates_rumor_and_analysis(tmp_path, db):
    title = f"md-import-{uuid4().hex[:8]}"
    md_content = "Officials clearly debunked this rumor."
    md = write_md(tmp_path, md_content, filename=f"{title}.md")
    response = StructuredRumorAnalysis(
        title=title, summary="summary", rumor_content="content",
        truth_content="truth", status=RumorStatus.FAKE,
        tags=["test"], source_urls=None,
        analysis_summary="Fake", truthfulness_score=0.1, evidence="Debunked.",
    )

    stats = import_md_file(md, analyzer=FakeAnalyzer([response]))

    assert stats.succeeded == 1
    expected_slug = f"{slugify(title)}-{hash_suffix(md_content)}"
    rumor = get_rumor_by_slug(db, expected_slug)
    assert rumor is not None
    analysis = get_analysis_by_rumor_id(db, rumor.id)
    assert analysis is not None
    assert analysis.summary == "Fake"
