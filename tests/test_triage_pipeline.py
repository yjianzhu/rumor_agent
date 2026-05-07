"""Tests for Stage 2: triage minimal filter and LLM output parsing."""

import json

import pytest

from src.ingest.triage import _build_llm_input, _format_comments, _is_noise, _parse_events


class TestIsNoise:
    def test_both_empty(self):
        assert _is_noise({"title": "", "description": ""}) is True

    def test_both_none(self):
        assert _is_noise({}) is True

    def test_title_only_spaces(self):
        assert _is_noise({"title": "   ", "description": ""}) is True

    def test_too_short(self):
        assert _is_noise({"title": "AB", "description": "CD"}) is True

    def test_title_long_enough(self):
        assert _is_noise({"title": "这是一段足够长的标题", "description": ""}) is False

    def test_desc_long_enough(self):
        assert _is_noise({"title": "", "description": "这是一段足够长的描述文字"}) is False

    def test_combined_length(self):
        assert _is_noise({"title": "1234", "description": "5678"}) is False

    def test_combined_exactly_eight(self):
        assert _is_noise({"title": "1234", "description": "5678"}) is False

    def test_combined_seven_is_noise(self):
        assert _is_noise({"title": "123", "description": "4567"}) is True

    def test_combined_too_short(self):
        assert _is_noise({"title": "12", "description": "345"}) is True


class TestParseEvents:
    def test_valid_events(self):
        raw = json.dumps([
            {
                "title": "争议标题A",
                "content": "争议内容描述",
                "source_urls": ["https://b.com/1", "https://xhs.com/2"],
                "controversy_type": "安全",
            },
            {
                "title": "争议标题B",
                "content": "另一个争议",
                "source_urls": ["https://b.com/3"],
                "controversy_type": "营销",
            },
        ])
        events = _parse_events(raw)
        assert len(events) == 2
        assert events[0]["title"] == "争议标题A"
        assert events[0]["controversy_type"] == "安全"
        assert len(events[0]["source_urls"]) == 2
        assert events[1]["title"] == "争议标题B"

    def test_empty_array(self):
        events = _parse_events("[]")
        assert events == []

    def test_markdown_fenced(self):
        inner = json.dumps([{
            "title": "标题",
            "content": "内容",
            "source_urls": [],
            "controversy_type": "其他",
        }])
        raw = f"```json\n{inner}\n```"
        events = _parse_events(raw)
        assert len(events) == 1
        assert events[0]["title"] == "标题"

    def test_skips_empty_title(self):
        raw = json.dumps([
            {"title": "", "content": "no title", "source_urls": [], "controversy_type": "其他"},
            {"title": "有标题", "content": "ok", "source_urls": [], "controversy_type": "其他"},
        ])
        events = _parse_events(raw)
        assert len(events) == 1
        assert events[0]["title"] == "有标题"

    def test_missing_controversy_type_defaults(self):
        raw = json.dumps([{
            "title": "标题",
            "content": "内容",
            "source_urls": ["https://example.com"],
        }])
        events = _parse_events(raw)
        assert events[0]["controversy_type"] == "其他"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_events("not json")

    def test_non_array_raises(self):
        with pytest.raises(ValueError, match="JSON array"):
            _parse_events('{"title": "not an array"}')

    def test_url_whitelist_strips_hallucinated_urls(self):
        raw = json.dumps([{
            "title": "保留事件",
            "content": "ok",
            "source_urls": [
                "https://b.com/real-1",      # in whitelist
                "https://evil.com/fake",     # hallucinated
                "https://b.com/real-2",      # in whitelist
            ],
            "controversy_type": "其他",
        }])
        allowed = {"https://b.com/real-1", "https://b.com/real-2"}
        events = _parse_events(raw, allowed_urls=allowed)

        assert len(events) == 1
        assert events[0]["source_urls"] == ["https://b.com/real-1", "https://b.com/real-2"]

    def test_url_whitelist_drops_event_with_no_real_sources(self):
        raw = json.dumps([
            {
                "title": "全幻觉事件",
                "content": "all fake",
                "source_urls": ["https://evil.com/a", "https://evil.com/b"],
                "controversy_type": "其他",
            },
            {
                "title": "保留事件",
                "content": "real",
                "source_urls": ["https://b.com/real"],
                "controversy_type": "其他",
            },
        ])
        allowed = {"https://b.com/real"}
        events = _parse_events(raw, allowed_urls=allowed)

        assert len(events) == 1
        assert events[0]["title"] == "保留事件"


class TestTriageRawJsonl:
    def test_multi_file_input(self, tmp_path):
        """triage_raw_jsonl accepts multiple files and merges them."""
        from unittest.mock import patch
        from src.ingest.triage import triage_raw_jsonl

        bili = tmp_path / "bili_20260406_120000.jsonl"
        xhs = tmp_path / "xhs_20260406_120000.jsonl"

        bili.write_text(json.dumps({
            "title": "B站视频标题足够长的内容",
            "description": "描述",
            "arcurl": "https://b.com/1",
            "bvid": "BV_TEST_1",
            "keyword": "测试",
        }) + "\n", encoding="utf-8")

        xhs.write_text(json.dumps({
            "title": "小红书笔记标题足够长的内容",
            "description": "描述",
            "source_url": "https://xhs.com/1",
            "note_id": "note-test-1",
            "keyword": "测试",
        }) + "\n", encoding="utf-8")

        mock_events = json.dumps([{
            "title": "测试争议",
            "content": "争议内容",
            "source_urls": ["https://b.com/1", "https://xhs.com/1"],
            "controversy_type": "其他",
        }])

        with patch("src.ingest.triage.llm_chat", return_value=mock_events):
            out = triage_raw_jsonl([bili, xhs], candidate_dir=tmp_path / "out")

        assert out.exists()
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["title"] == "测试争议"
        assert event["keyword"] == "测试"
        assert len(event["source_urls"]) == 2
        assert event["source_refs"] == [
            {"url": "https://b.com/1", "raw_id": "BV_TEST_1", "platform": "bilibili"},
            {"url": "https://xhs.com/1", "raw_id": "note-test-1", "platform": "xhs"},
        ]

    def test_all_noise_no_llm_call(self, tmp_path):
        """When all records are noise, LLM is not called."""
        from unittest.mock import patch, MagicMock
        from src.ingest.triage import triage_raw_jsonl

        raw = tmp_path / "bili_20260406_120000.jsonl"
        raw.write_text(json.dumps({
            "title": "",
            "description": "",
            "arcurl": "https://b.com/1",
        }) + "\n", encoding="utf-8")

        mock_llm = MagicMock()
        with patch("src.ingest.triage.llm_chat", mock_llm):
            out = triage_raw_jsonl([raw], candidate_dir=tmp_path / "out")

        mock_llm.assert_not_called()
        assert out.exists()
        content = out.read_text(encoding="utf-8").strip()
        assert content == ""


class TestFormatComments:
    def test_skips_blank_text(self):
        out = _format_comments([
            {"text": "  ", "like": 5, "author": "X"},
            {"text": "实质评论", "like": 10, "author": "Y"},
        ])
        assert out == ["Y(👍10): 实质评论"]

    def test_anonymous_fallback(self):
        out = _format_comments([{"text": "t", "like": 0, "author": ""}])
        assert out == ["匿名(👍0): t"]

    def test_non_list_returns_empty(self):
        assert _format_comments(None) == []
        assert _format_comments("nope") == []


class TestBuildLLMInput:
    def test_includes_comments_field(self):
        records = [{
            "title": "t",
            "description": "d",
            "arcurl": "https://b.com/1",
            "author": "作者",
            "rank_meta": {"play": 1000},
            "comments": [{"text": "评论A", "like": 5, "author": "用户"}],
        }]
        payload = json.loads(_build_llm_input(records, keyword="kw"))
        assert payload["items"][0]["comments"] == ["用户(👍5): 评论A"]

    def test_missing_comments_serializes_empty(self):
        records = [{"title": "t", "description": "d", "arcurl": "https://b.com/1"}]
        payload = json.loads(_build_llm_input(records))
        assert payload["items"][0]["comments"] == []
