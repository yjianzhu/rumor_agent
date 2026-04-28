"""Tests for Stage 1: bilibili_collector parsing & cleaning utilities."""

import json
from pathlib import Path

import pytest

from src.ingest.bilibili_collector import (
    strip_html,
    normalize_url,
    _parse_items,
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
