"""Tests for Stage 3: fusion adapter and grouping logic."""

import json
from pathlib import Path

import pytest

from src.ingest.fusion import (
    BilibiliAdapter,
    UnifiedRecord,
    _event_key,
    fuse_candidates,
)


class TestBilibiliAdapter:
    def test_skips_non_followup(self):
        adapter = BilibiliAdapter()
        raw = {"needs_followup": False, "title": "x", "arcurl": "https://..."}
        assert adapter.adapt(raw) is None

    def test_adapts_followup(self):
        adapter = BilibiliAdapter()
        raw = {
            "needs_followup": True,
            "title": "可疑视频",
            "description": "描述",
            "arcurl": "https://www.bilibili.com/video/BV1xx",
            "bvid": "BV1xx",
            "keyword": "测试",
            "fetched_at": "2026-01-01T00:00:00Z",
            "followup_reason": "reason",
            "followup_queries": ["q1"],
            "rank_meta": {"play": 100},
        }
        rec = adapter.adapt(raw)
        assert rec is not None
        assert rec.platform == "bilibili"
        assert rec.title == "可疑视频"
        assert rec.source_url == "https://www.bilibili.com/video/BV1xx"


class TestEventKey:
    def test_short_title(self):
        rec = UnifiedRecord(platform="b", title="AB", description="", source_url="u")
        key = _event_key(rec)
        assert key == "ab"

    def test_long_title_truncated(self):
        rec = UnifiedRecord(platform="b", title="A" * 50, description="", source_url="u")
        key = _event_key(rec)
        assert len(key) == 30


class TestFuseCandidates:
    def test_basic_fusion(self, tmp_path: Path):
        records = [
            {
                "needs_followup": True,
                "title": "事件A详情",
                "description": "desc",
                "arcurl": "https://b.com/1",
                "bvid": "BV1",
                "keyword": "kw",
                "fetched_at": "2026-01-01T00:00:00Z",
                "followup_reason": "r",
                "followup_queries": [],
                "rank_meta": {},
            },
            {
                "needs_followup": False,
                "title": "广告视频",
                "description": "",
                "arcurl": "https://b.com/2",
            },
        ]
        cand_path = tmp_path / "bili_20260101_120000_candidate.jsonl"
        with cand_path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        out = fuse_candidates([cand_path], fused_dir=tmp_path / "fused")
        assert out.exists()

        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        fused = json.loads(lines[0])
        assert fused["title"] == "事件A详情"
        assert "https://b.com/1" in fused["source_urls"]
