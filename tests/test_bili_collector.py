"""Tests for Stage 1: bilibili_collector parsing & cleaning utilities."""

import asyncio
import json
from pathlib import Path

import pytest

from src.ingest import bilibili_collector
from src.ingest.bilibili_collector import (
    _fetch_comments_for_bvid,
    _parse_items,
    normalize_url,
    strip_html,
)


class TestStripHtml:
    def test_removes_em_tags(self):
        assert strip_html('<em class="keyword">雷军</em>发布') == "雷军发布"

    def test_plain_text_unchanged(self):
        assert strip_html("plain text") == "plain text"

    def test_nested_tags(self):
        assert strip_html("<b><i>bold italic</i></b>") == "bold italic"

    def test_empty(self):
        assert strip_html("") == ""


class TestNormalizeUrl:
    def test_http_to_https(self):
        assert normalize_url("http://www.bilibili.com/video/123") == \
            "https://www.bilibili.com/video/123"

    def test_https_unchanged(self):
        url = "https://www.bilibili.com/video/123"
        assert normalize_url(url) == url

    def test_empty(self):
        assert normalize_url("") == ""


class TestParseItems:
    def test_basic_parsing(self):
        payload = {
            "result": [
                {
                    "title": '<em class="keyword">test</em> video',
                    "description": "desc here",
                    "arcurl": "http://www.bilibili.com/video/av123",
                    "bvid": "BV1xx",
                    "rank_offset": 1,
                    "play": 1000,
                    "like": 50,
                    "video_review": 10,
                },
            ]
        }
        rows = _parse_items(payload, keyword="test")
        assert len(rows) == 1
        r = rows[0]
        assert r["keyword"] == "test"
        assert r["title"] == "test video"
        assert "em" not in r["title"]
        assert r["arcurl"].startswith("https://")
        assert r["bvid"] == "BV1xx"
        assert r["rank_meta"]["play"] == 1000

    def test_empty_result(self):
        assert _parse_items({"result": []}, keyword="x") == []
        assert _parse_items({}, keyword="x") == []


class TestFetchComments:
    @staticmethod
    def _payload():
        return {
            "replies": [
                {
                    "content": {"message": "高赞质疑"},
                    "like": 1234,
                    "member": {"uname": "网友A"},
                    "reply_control": {"location": "IP属地：北京"},
                },
                {
                    "content": {"message": "  "},
                    "like": 0,
                    "member": {"uname": "空评论"},
                },
                {
                    "content": {"message": "二楼评论"},
                    "like": 50,
                    "member": {"uname": "网友B"},
                },
            ],
        }

    def test_top_n_zero_skips_call(self, monkeypatch):
        called = {"n": 0}

        async def fake_get_comments(*a, **kw):
            called["n"] += 1
            return {}

        monkeypatch.setattr(bilibili_collector.comment, "get_comments", fake_get_comments)
        out = asyncio.run(_fetch_comments_for_bvid("BV1xx", 0))
        assert out == []
        assert called["n"] == 0

    def test_empty_bvid(self):
        assert asyncio.run(_fetch_comments_for_bvid("", 5)) == []

    def test_parses_replies_skips_blank(self, monkeypatch):
        async def fake_get_comments(*a, **kw):
            return self._payload()

        class FakeVideo:
            def __init__(self, bvid):
                pass

            def get_aid(self):
                return 12345

        monkeypatch.setattr(bilibili_collector.comment, "get_comments", fake_get_comments)
        monkeypatch.setattr(bilibili_collector.video, "Video", FakeVideo)

        out = asyncio.run(_fetch_comments_for_bvid("BV1xx", 5))
        assert len(out) == 2
        assert out[0]["text"] == "高赞质疑"
        assert out[0]["like"] == 1234
        assert out[0]["author"] == "网友A"
        assert out[0]["ip"] == "IP属地：北京"
        assert out[1]["text"] == "二楼评论"

    def test_truncates_to_top_n(self, monkeypatch):
        async def fake_get_comments(*a, **kw):
            return self._payload()

        class FakeVideo:
            def __init__(self, bvid):
                pass

            def get_aid(self):
                return 1

        monkeypatch.setattr(bilibili_collector.comment, "get_comments", fake_get_comments)
        monkeypatch.setattr(bilibili_collector.video, "Video", FakeVideo)
        out = asyncio.run(_fetch_comments_for_bvid("BV1xx", 1))
        assert len(out) == 1

    def test_returns_empty_on_exception(self, monkeypatch):
        async def fake_get_comments(*a, **kw):
            raise RuntimeError("network down")

        class FakeVideo:
            def __init__(self, bvid):
                pass

            def get_aid(self):
                return 1

        monkeypatch.setattr(bilibili_collector.comment, "get_comments", fake_get_comments)
        monkeypatch.setattr(bilibili_collector.video, "Video", FakeVideo)
        assert asyncio.run(_fetch_comments_for_bvid("BV1xx", 5)) == []
