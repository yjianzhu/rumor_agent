"""Tests for src/llm/client.py: tenacity retry & context-length truncation."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.config import settings
from src.db.models import RumorStatus
from src.db.schemas import _RumorSampleIn, StructuredRumorAnalysis


# ─── tenacity retry / endpoint fallback ──────────────────────────────────────

class TestLlmRetry:
    def _make_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": text}}]}
        resp.raise_for_status.return_value = None
        return resp

    def test_retry_succeeds_on_second_attempt(self):
        from src.llm import client as llm_client

        expected_json = StructuredRumorAnalysis(
            title="T", summary=None, rumor_content="c", truth_content=None,
            status=RumorStatus.DUBIOUS, tags=None, source_urls=None,
            analysis_summary=None, truthfulness_score=0.5, evidence="e",
        ).model_dump_json()

        side_effects = [
            ConnectionError("transient"),
            self._make_response(expected_json),
        ]
        with patch.object(llm_client.curl_requests, "post", side_effect=side_effects) as mock_post:
            result = llm_client.analyze_structured(_RumorSampleIn(raw_text="test content"))

        assert mock_post.call_count == 2
        assert result.title == "T"

    def test_retry_exhausted_raises(self):
        from src.llm import client as llm_client

        with patch.object(
            llm_client.curl_requests, "post",
            side_effect=ConnectionError("persistent failure"),
        ):
            with pytest.raises(RuntimeError, match="endpoints failed"):
                llm_client.analyze_structured(_RumorSampleIn(raw_text="test content"))


# ─── Context length truncation ───────────────────────────────────────────────

class TestContextTruncation:
    def test_char_fallback_truncation(self, caplog):
        from src.llm.client import _truncate_sample

        long_text = "x" * (settings.LLM_MAX_INPUT_CHARS + 1000)
        sample = _RumorSampleIn(raw_text=long_text)

        with caplog.at_level(logging.WARNING):
            result = _truncate_sample(sample)

        assert len(result.raw_text) == settings.LLM_MAX_INPUT_CHARS
        assert "truncated" in caplog.text

    def test_short_text_not_truncated(self):
        from src.llm.client import _truncate_sample

        sample = _RumorSampleIn(raw_text="short text")
        result = _truncate_sample(sample)

        assert result.raw_text == "short text"
