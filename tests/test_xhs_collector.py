"""Tests for Stage 1: xhs_collector parsing & URL utilities."""

import json
from datetime import datetime, timedelta

import pytest

from src.ingest import xhs_collector
from src.ingest.xhs_collector import _apply_local_filters, build_note_url, parse_feed


class TestBuildNoteUrl:
    def test_normal(self):
        url = build_note_url("abc123", "tok-xyz")
        assert url == (
            "https://www.xiaohongshu.com/explore/abc123"
            "?xsec_token=tok-xyz&xsec_source=pc_search"
        )

    def test_empty_id(self):
        assert build_note_url("", "tok") == ""

    def test_empty_token(self):
        assert build_note_url("abc", "") == ""

    def test_both_empty(self):
        assert build_note_url("", "") == ""


class TestParseFeed:
    SAMPLE_FEED = {
        "id": "69d3a976000000001a024cc2",
        "xsecToken": "ABBNFKvYONI6R58FcQnWFfics=",
        "noteCard": {
            "displayTitle": "测试标题",
            "user": {
                "userId": "u123",
                "nickname": "测试作者",
                "nickName": "测试作者",
            },
            "interactInfo": {
                "likedCount": "201",
                "commentCount": "42",
            },
            "cover": {
                "urlDefault": "http://example.com/cover.jpg",
            },
        },
    }

    def test_basic_parsing(self):
        row = parse_feed(
            self.SAMPLE_FEED,
            keyword="春招",
            rank_offset=0,
        )
        assert row["keyword"] == "春招"
        assert row["title"] == "测试标题"
        assert row["author"] == "测试作者"
        assert row["note_id"] == "69d3a976000000001a024cc2"
        assert row["xsec_token"] == "ABBNFKvYONI6R58FcQnWFfics="
        assert "xiaohongshu.com/explore/69d3a976" in row["source_url"]
        assert row["rank_meta"]["liked_count"] == "201"
        assert row["rank_meta"]["comment_count"] == "42"
        assert row["rank_meta"]["rank_offset"] == 0
        assert row["description"] == ""

    def test_missing_notecard(self):
        row = parse_feed(
            {"id": "x", "xsecToken": "t"},
            keyword="kw",
            rank_offset=5,
        )
        assert row["title"] == ""
        assert row["author"] == ""
        assert row["rank_meta"]["rank_offset"] == 5

    def test_empty_feed(self):
        row = parse_feed(
            {},
            keyword="kw",
            rank_offset=0,
        )
        assert row["note_id"] == ""
        assert row["source_url"] == ""

    def test_nickname_fallback(self):
        """When nickname is empty, should fall back to nickName."""
        feed = {
            "id": "x",
            "xsecToken": "t",
            "noteCard": {
                "user": {"nickname": "", "nickName": "备用名"},
            },
        }
        row = parse_feed(feed, keyword="k", rank_offset=0)
        assert row["author"] == "备用名"


class TestLocalSearchFilters:
    @staticmethod
    def _feed(created_at: datetime, comments: str, title: str) -> dict:
        return {
            "id": f"{int(created_at.timestamp()):08x}0000000012345678",
            "noteCard": {
                "displayTitle": title,
                "interactInfo": {"commentCount": comments},
            },
        }

    def test_publish_time_and_comment_sort_are_applied_locally(self):
        now = datetime.now()
        feeds = [
            self._feed(now - timedelta(hours=2), "3", "recent-low"),
            self._feed(now - timedelta(hours=3), "42", "recent-high"),
            self._feed(now - timedelta(days=2), "999", "old-high"),
        ]

        rows = _apply_local_filters(
            feeds,
            {"publish_time": "一天内", "sort_by": "最多评论"},
        )

        assert [row["noteCard"]["displayTitle"] for row in rows] == [
            "recent-high",
            "recent-low",
        ]

    def test_search_does_not_send_publish_time_to_mcp(self, monkeypatch):
        captured = {}

        def fake_tool_call(url, headers, tool_name, arguments, **kwargs):
            captured["arguments"] = arguments
            return json.dumps({"feeds": []})

        monkeypatch.setattr(xhs_collector, "_mcp_tool_call", fake_tool_call)

        xhs_collector._search_feeds(
            "http://127.0.0.1:18060/mcp",
            {},
            "雷军",
            {"publish_time": "一天内", "sort_by": "最多评论"},
        )

        assert captured["arguments"]["filters"] == {"sort_by": "最多评论"}
