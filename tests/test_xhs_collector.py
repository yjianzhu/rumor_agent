"""Tests for Stage 1: xhs_collector parsing & URL utilities."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ingest import xhs_collector
from src.ingest.xhs_collector import _extract_comments, build_note_url, parse_feed
from src.main import main


class TestBuildNoteUrl:
    def test_normal(self):
        url = build_note_url("abc123")
        assert url == "https://www.xiaohongshu.com/explore/abc123"

    def test_empty_id(self):
        assert build_note_url("") == ""


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


class TestSearchFeedsForwarding:
    def test_filters_are_forwarded_to_mcp(self, monkeypatch):
        captured = {}

        def fake_tool_call(url, headers, tool_name, arguments, **kwargs):
            captured["arguments"] = arguments
            return json.dumps({"feeds": []})

        monkeypatch.setattr(xhs_collector, "_mcp_tool_call", fake_tool_call)

        xhs_collector._search_feeds(
            "http://127.0.0.1:18060/mcp",
            {},
            "雷军",
            {"publish_time": "一周内", "sort_by": "最多评论", "note_type": "视频"},
        )

        assert captured["arguments"] == {
            "keyword": "雷军",
            "filters": {"publish_time": "一周内", "sort_by": "最多评论", "note_type": "视频"},
        }

    def test_no_filters_sends_keyword_only(self, monkeypatch):
        captured = {}

        def fake_tool_call(url, headers, tool_name, arguments, **kwargs):
            captured["arguments"] = arguments
            return json.dumps({"feeds": []})

        monkeypatch.setattr(xhs_collector, "_mcp_tool_call", fake_tool_call)

        xhs_collector._search_feeds("http://127.0.0.1:18060/mcp", {}, "雷军", None)
        assert captured["arguments"] == {"keyword": "雷军"}

    def test_returns_feeds_unmodified(self, monkeypatch):
        feeds = [{"id": "a"}, {"id": "b"}]

        def fake_tool_call(url, headers, tool_name, arguments, **kwargs):
            return json.dumps({"feeds": feeds})

        monkeypatch.setattr(xhs_collector, "_mcp_tool_call", fake_tool_call)
        out = xhs_collector._search_feeds("u", {}, "kw", {"sort_by": "最多评论"})
        assert out == feeds


class TestExtractComments:
    DATA_WITH_COMMENTS = {
        "note": {"noteId": "x"},
        "comments": {
            "list": [
                {
                    "content": "评论一",
                    "likeCount": "29",
                    "ipLocation": "广东",
                    "userInfo": {"nickname": "用户A"},
                },
                {
                    "content": "  ",
                    "likeCount": "5",
                    "userInfo": {"nickname": "空评论"},
                },
                {
                    "content": "评论三",
                    "likeCount": "bad",
                    "ipLocation": "",
                    "userInfo": {"nickname": "用户C"},
                },
            ],
        },
    }

    def test_top_n_zero_returns_empty(self):
        assert _extract_comments(self.DATA_WITH_COMMENTS, 0) == []

    def test_skips_blank_text_and_handles_bad_like(self):
        out = _extract_comments(self.DATA_WITH_COMMENTS, 10)
        assert len(out) == 2
        assert out[0] == {"text": "评论一", "like": 29, "author": "用户A", "ip": "广东"}
        assert out[1]["like"] == 0
        assert out[1]["author"] == "用户C"

    def test_truncates_to_top_n(self):
        out = _extract_comments(self.DATA_WITH_COMMENTS, 1)
        assert len(out) == 1

    def test_empty_data(self):
        assert _extract_comments({}, 5) == []
        assert _extract_comments({"comments": {}}, 5) == []
        assert _extract_comments({"note": {"comments": {"list": [{"content": "x"}]}}}, 5) == []


class TestCollectXhsCli:
    def test_defaults_target_recent_important_results(self):
        with patch("src.ingest.xhs_collector.collect_xhs", return_value=Path("xhs.jsonl")) as collect:
            assert main(["--collect-xhs", "kw"]) == 0

        collect.assert_called_once_with(
            "kw",
            filters={"sort_by": "最多评论", "publish_time": "一天内"},
            max_items=None,
        )

    def test_explicit_filters_are_preserved(self):
        with patch("src.ingest.xhs_collector.collect_xhs", return_value=Path("xhs.jsonl")) as collect:
            assert main([
                "--collect-xhs", "kw",
                "--xhs-sort-by", "最新",
                "--xhs-publish-time", "一周内",
                "--xhs-note-type", "视频",
                "--xhs-max-items", "3",
            ]) == 0

        collect.assert_called_once_with(
            "kw",
            filters={"sort_by": "最新", "publish_time": "一周内", "note_type": "视频"},
            max_items=3,
        )
