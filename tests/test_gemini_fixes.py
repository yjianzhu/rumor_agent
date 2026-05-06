"""Tests for LLM retry, context length truncation, batch commit, and semantic dedup."""
from __future__ import annotations

import io
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.config import settings
from src.db.schemas import _RumorSampleIn, StructuredRumorAnalysis
from src.db.models import RumorStatus
from src.main import import_jsonl_file

from tests.conftest import write_jsonl


# ─── 1. tenacity retry ─────────────────────────────────────────────────────

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

        # All attempts fail with a retriable error → tenacity exhausts retries on
        # the first endpoint, fallback tries the next endpoint (also fails),
        # final RuntimeError is raised by _call_with_fallback.
        with patch.object(
            llm_client.curl_requests, "post",
            side_effect=ConnectionError("persistent failure"),
        ):
            with pytest.raises(RuntimeError, match="endpoints failed"):
                llm_client.analyze_structured(_RumorSampleIn(raw_text="test content"))


# ─── 2. Context length truncation ──────────────────────────────────────────

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


# ─── 3. Batch commit ───────────────────────────────────────────────────────

class TestBatchCommit:
    def test_batch_plus_one_all_imported(self, tmp_path):
        """BATCH_SIZE + 1 records should all succeed in dry-run mode."""
        count = settings.IMPORT_BATCH_SIZE + 1
        rows = [{"title": f"Rumor {i}", "rumor_content": f"content {i}"} for i in range(count)]
        path = write_jsonl(tmp_path, rows)

        stats = import_jsonl_file(path, dry_run=True)

        assert stats.processed == count
        assert stats.succeeded == count
        assert stats.failed == 0

    def test_bad_record_does_not_affect_good_ones(self, tmp_path):
        """A bad record in the middle shouldn't prevent good records from succeeding."""
        rows = [
            {"title": "Good 1", "rumor_content": "content"},
            {"rumor_content": "missing title"},  # bad — missing title
            {"title": "Good 2", "rumor_content": "content"},
        ]
        path = write_jsonl(tmp_path, rows)

        stats = import_jsonl_file(path, dry_run=True)

        assert stats.succeeded == 2
        assert stats.failed == 1


# ─── 4. Semantic dedup ─────────────────────────────────────────────────────

class TestSemanticDedup:
    def test_high_similarity_rejected(self):
        """When get_embedding returns identical vectors, dedup should reject."""
        from src.main import _resolve_slug
        vec = [1.0] * settings.EMBEDDING_DIM

        db = MagicMock()
        # Pass 1: slug not taken
        with patch("src.main.get_rumor_by_slug", return_value=None):
            # Pass 2: semantic match found
            similar_rumor = MagicMock()
            similar_rumor.slug = "existing-slug"
            with patch("src.main.find_similar_rumor", return_value=similar_rumor):
                result = _resolve_slug(db, "test-slug", "content", vec)

        assert result is None  # rejected as duplicate

    def test_low_similarity_passes(self):
        """When find_similar_rumor returns None, slug should be returned."""
        from src.main import _resolve_slug

        vec = [1.0] * settings.EMBEDDING_DIM

        db = MagicMock()
        with patch("src.main.get_rumor_by_slug", return_value=None):
            with patch("src.main.find_similar_rumor", return_value=None):
                result = _resolve_slug(db, "test-slug", "content", vec)

        assert result == "test-slug"

    def test_no_embedding_falls_back_to_hash(self):
        """When embedding is None, only hash dedup applies."""
        from src.main import _resolve_slug

        db = MagicMock()
        with patch("src.main.get_rumor_by_slug", return_value=None):
            result = _resolve_slug(db, "test-slug", "content", None)

        assert result == "test-slug"

    def test_safe_get_embedding_returns_none_on_failure(self):
        from src.main import _safe_get_embedding

        with patch("src.main.get_embedding", side_effect=RuntimeError("API down")):
            result = _safe_get_embedding("test text")

        assert result is None
