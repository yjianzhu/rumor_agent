"""Tests for the --run-pipeline orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.main import PipelineSummary, run_pipeline


def _make_bili_raw(out_dir: Path, keyword: str, probe: str, n: int = 1) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bili_{probe}_{keyword}.jsonl"
    rows = [{
        "keyword": keyword,
        "title": f"bili-{keyword}-{probe}-{i} 标题足够长用来过滤",
        "description": f"bili 描述 {probe}",
        "arcurl": f"https://www.bilibili.com/video/{probe}{i}",
        "bvid": f"BV{probe}{i}",
        "rank_meta": {"rank_offset": i, "play": 1000, "like": 50, "danmaku": 5},
    } for i in range(n)]
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _make_xhs_raw(out_dir: Path, keyword: str, probe: str, n: int = 1) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"xhs_{probe}_{keyword}.jsonl"
    rows = [{
        "keyword": keyword,
        "title": f"xhs-{keyword}-{probe}-{i} 标题足够长用来过滤",
        "description": f"xhs 描述 {probe}",
        "source_url": f"https://xiaohongshu.com/explore/{probe}{i}",
        "note_id": f"{probe}{i}",
        "rank_meta": {"rank_offset": i, "liked_count": "100", "comment_count": "10"},
    } for i in range(n)]
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _fake_triage_writer(out_dir: Path, probe: str, n_events: int):
    """Return a callable that writes a candidate JSONL and returns its path."""
    def _writer(raw_paths, *, candidate_dir=None):
        target = (candidate_dir or out_dir)
        target.mkdir(parents=True, exist_ok=True)
        out = target / f"candidate_{probe}.jsonl"
        events = [{
            "title": f"争议 {probe}-{i}",
            "content": f"内容 {probe}-{i}",
            "source_urls": [f"https://x.com/{probe}/{i}"],
            "controversy_type": "其他",
            "keyword": "test",
        } for i in range(n_events)]
        with out.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return out
    return _writer


@pytest.fixture
def patched_keywords(monkeypatch):
    """Replace settings.COLLECT_KEYWORDS for one test."""
    def _set(keywords: list[str]):
        from src.config import settings
        monkeypatch.setattr(settings, "COLLECT_KEYWORDS", keywords)
    return _set


class TestRunPipeline:
    def test_happy_path(self, db, tmp_path, patched_keywords):
        probe = uuid4().hex[:6]
        patched_keywords([f"kw-{probe}-A", f"kw-{probe}-B"])
        raw_dir = tmp_path / "raw"
        cand_dir = tmp_path / "candidates"

        with patch("src.ingest.bilibili_collector.collect_bilibili",
                   side_effect=lambda kw, **_: _make_bili_raw(raw_dir, kw, probe)), \
             patch("src.ingest.xhs_collector.collect_xhs",
                   side_effect=lambda kw, **_: _make_xhs_raw(raw_dir, kw, probe)), \
             patch("src.ingest.triage.triage_raw_jsonl",
                   side_effect=_fake_triage_writer(cand_dir, probe, n_events=3)), \
             patch("src.main._safe_get_embedding", return_value=None):
            summary = run_pipeline()

        assert summary.keywords == 2
        assert len(summary.raw_files) == 4  # 2 keywords × 2 platforms
        assert summary.candidate_file is not None
        assert summary.candidate_file.exists()
        assert summary.import_stats is not None
        assert summary.import_stats.processed == 3
        assert summary.import_stats.succeeded == 3
        assert summary.import_stats.failed == 0
        assert summary.collect_failures == []
        assert summary.failed is False

    def test_xhs_failures_do_not_block_bili(self, db, tmp_path, patched_keywords):
        probe = uuid4().hex[:6]
        patched_keywords([f"kw-{probe}-A"])
        raw_dir = tmp_path / "raw"
        cand_dir = tmp_path / "candidates"

        def fail_xhs(kw, **_):
            raise RuntimeError("xhs not logged in")

        with patch("src.ingest.bilibili_collector.collect_bilibili",
                   side_effect=lambda kw, **_: _make_bili_raw(raw_dir, kw, probe)), \
             patch("src.ingest.xhs_collector.collect_xhs", side_effect=fail_xhs), \
             patch("src.ingest.triage.triage_raw_jsonl",
                   side_effect=_fake_triage_writer(cand_dir, probe, n_events=1)), \
             patch("src.main._safe_get_embedding", return_value=None):
            summary = run_pipeline()

        assert len(summary.raw_files) == 1
        assert any("xhs:" in fail for fail in summary.collect_failures)
        assert summary.candidate_file is not None
        assert summary.import_stats.succeeded == 1
        assert summary.failed is False  # collector failures alone don't fail the run

    def test_all_collectors_fail_skips_triage_and_import(self, db, tmp_path, patched_keywords):
        probe = uuid4().hex[:6]
        patched_keywords([f"kw-{probe}-A"])

        with patch("src.ingest.bilibili_collector.collect_bilibili",
                   side_effect=RuntimeError("bili down")), \
             patch("src.ingest.xhs_collector.collect_xhs",
                   side_effect=RuntimeError("xhs down")):
            summary = run_pipeline()

        assert summary.raw_files == []
        assert len(summary.collect_failures) == 2
        assert summary.candidate_file is None
        assert summary.import_stats is None
        assert summary.triage_failed is True
        assert summary.failed is True

    def test_triage_failure_skips_import(self, db, tmp_path, patched_keywords):
        probe = uuid4().hex[:6]
        patched_keywords([f"kw-{probe}-A"])
        raw_dir = tmp_path / "raw"

        with patch("src.ingest.bilibili_collector.collect_bilibili",
                   side_effect=lambda kw, **_: _make_bili_raw(raw_dir, kw, probe)), \
             patch("src.ingest.xhs_collector.collect_xhs",
                   side_effect=lambda kw, **_: _make_xhs_raw(raw_dir, kw, probe)), \
             patch("src.ingest.triage.triage_raw_jsonl",
                   side_effect=RuntimeError("LLM endpoints all failed")):
            summary = run_pipeline()

        assert len(summary.raw_files) == 2
        assert summary.candidate_file is None
        assert summary.import_stats is None
        assert summary.triage_failed is True
        assert summary.failed is True

    def test_empty_keywords_aborts(self, db, patched_keywords):
        patched_keywords([])
        summary = run_pipeline()

        assert summary.keywords == 0
        assert summary.triage_failed is True
        assert summary.failed is True
