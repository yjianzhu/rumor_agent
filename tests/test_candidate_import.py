"""Tests for candidate JSONL import (controversy events → rumors table)."""

import json
import io

import pytest

from src.main import import_candidate_jsonl


class TestImportCandidateJsonl:
    def _make_candidate_file(self, tmp_path, events):
        path = tmp_path / "candidate_20260406_120000.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return path

    def test_dry_run_preview(self, tmp_path):
        events = [
            {
                "title": "小米SU7安全性争议",
                "content": "多方对小米SU7的碰撞安全表现存在分歧",
                "source_urls": ["https://b.com/1", "https://xhs.com/2"],
                "controversy_type": "安全",
                "keyword": "小米汽车",
            },
        ]
        path = self._make_candidate_file(tmp_path, events)
        buf = io.StringIO()
        stats = import_candidate_jsonl(path, dry_run=True, output=buf)

        assert stats.processed == 1
        assert stats.succeeded == 1
        assert stats.failed == 0

        output = buf.getvalue()
        assert "小米SU7安全性争议" in output
        assert "DUBIOUS" in output

    def test_empty_title_skipped(self, tmp_path):
        events = [
            {"title": "", "content": "no title", "source_urls": []},
        ]
        path = self._make_candidate_file(tmp_path, events)
        stats = import_candidate_jsonl(path, dry_run=True, output=io.StringIO())
        assert stats.processed == 1
        assert stats.failed == 1
        assert stats.succeeded == 0

    def test_tags_from_keyword_and_type(self, tmp_path):
        events = [
            {
                "title": "电饭煲涂层脱落争议事件",
                "content": "用户反馈涂层问题",
                "source_urls": ["https://xhs.com/1"],
                "controversy_type": "质量",
                "keyword": "小米",
            },
        ]
        path = self._make_candidate_file(tmp_path, events)
        buf = io.StringIO()
        import_candidate_jsonl(path, dry_run=True, output=buf)

        output = buf.getvalue()
        parsed = json.loads(output.split(": ", 1)[1])
        assert "小米" in parsed["tags"]
        assert "质量" in parsed["tags"]

    def test_limit_respected(self, tmp_path):
        events = [
            {"title": f"争议事件{i}", "content": "内容", "source_urls": []}
            for i in range(5)
        ]
        path = self._make_candidate_file(tmp_path, events)
        stats = import_candidate_jsonl(path, limit=2, dry_run=True, output=io.StringIO())
        assert stats.processed == 2
        assert stats.succeeded == 2

    def test_empty_file(self, tmp_path):
        path = self._make_candidate_file(tmp_path, [])
        stats = import_candidate_jsonl(path, dry_run=True, output=io.StringIO())
        assert stats.processed == 0
        assert stats.succeeded == 0
