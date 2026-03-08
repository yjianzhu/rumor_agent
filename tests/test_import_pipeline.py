import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from src.analyzer.analyzer import normalize_structured_analysis, slugify
from src.db.base import SessionLocal
from src.db.crud import delete_rumor, get_analysis_by_rumor_id, get_rumor_by_slug
from src.db.models import RumorStatus
from src.db.schemas import RumorSampleIn, StructuredRumorAnalysis
from src.main import import_jsonl_file


class FakeAnalyzer:
    def __init__(self, responses):
        self.responses = iter(responses)

    def analyze(self, sample):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class ImportPipelineTests(unittest.TestCase):
    def write_jsonl(self, rows: list[object]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl", encoding="utf-8")
        with handle:
            for row in rows:
                if isinstance(row, str):
                    handle.write(row + "\n")
                else:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_invalid_json_and_missing_raw_text_are_counted(self):
        path = self.write_jsonl([{"raw_text": "ok"}, {"title": "missing raw"}, '{"raw_text": '])
        output = io.StringIO()

        stats = import_jsonl_file(path, skip_analysis=True, output=output)

        self.assertEqual(stats.processed, 3)
        self.assertEqual(stats.succeeded, 1)
        self.assertEqual(stats.failed, 2)
        self.assertIn("Line 2", output.getvalue())
        self.assertIn("Line 3", output.getvalue())

    def test_dry_run_preserves_input_metadata(self):
        sample = {
            "raw_text": "Rumor notice with source https://example.com/a and internal warning.",
            "title": "Manual Title",
            "source_urls": ["https://seed.local/1"],
            "tags": ["public-service"],
        }
        response = StructuredRumorAnalysis(
            title="Model Title",
            summary="  Summary  ",
            rumor_content="ignored",
            truth_content="  Explanation  ",
            status=RumorStatus.FAKE,
            tags=["rumor", "public-service"],
            source_urls=["https://example.com/a", "https://seed.local/1"],
            analysis_summary="  Analysis summary ",
            truthfulness_score=0.8,
            evidence="  The text says it was debunked. ",
        )
        path = self.write_jsonl([sample])
        output = io.StringIO()

        stats = import_jsonl_file(path, dry_run=True, output=output, analyzer=FakeAnalyzer([response]))

        self.assertEqual(stats.succeeded, 1)
        preview = output.getvalue()
        self.assertIn("Manual Title", preview)
        self.assertIn("https://seed.local/1", preview)
        self.assertIn("https://example.com/a", preview)

    def test_missing_title_uses_model_title_for_slug(self):
        sample = {"raw_text": "This sample clearly says the claim was debunked by officials."}
        response = StructuredRumorAnalysis(
            title="Model Generated Title",
            summary=None,
            rumor_content="ignored",
            truth_content=None,
            status=RumorStatus.FAKE,
            tags=None,
            source_urls=None,
            analysis_summary=None,
            truthfulness_score=0.9,
            evidence="Officials debunked the claim.",
        )
        path = self.write_jsonl([sample])
        output = io.StringIO()

        stats = import_jsonl_file(path, dry_run=True, output=output, analyzer=FakeAnalyzer([response]))

        self.assertEqual(stats.succeeded, 1)
        self.assertIn("Model Generated Title", output.getvalue())
        self.assertIn(slugify("Model Generated Title"), output.getvalue())

    def test_invalid_model_output_is_counted_as_failure(self):
        sample = {"raw_text": "Plain text without a clear verdict."}
        try:
            StructuredRumorAnalysis.model_validate({})
        except ValidationError as exc:
            invalid_response = exc
        path = self.write_jsonl([sample])
        output = io.StringIO()

        stats = import_jsonl_file(path, dry_run=True, output=output, analyzer=FakeAnalyzer([invalid_response]))

        self.assertEqual(stats.failed, 1)
        self.assertIn("Line 1", output.getvalue())

    def test_no_verdict_signal_forces_dubious(self):
        sample = RumorSampleIn(raw_text="This is only an unverified retelling of a claim.")
        analysis = StructuredRumorAnalysis(
            title="Title",
            summary=None,
            rumor_content="ignored",
            truth_content=None,
            status=RumorStatus.TRUE,
            tags=None,
            source_urls=None,
            analysis_summary=None,
            truthfulness_score=0.7,
            evidence="Model overreached",
        )

        normalized = normalize_structured_analysis(sample, analysis)

        self.assertEqual(normalized.status, RumorStatus.DUBIOUS)

    def test_skip_analysis_only_prints_preview(self):
        path = self.write_jsonl([{"raw_text": "Preview only, do not call the LLM."}])
        output = io.StringIO()

        stats = import_jsonl_file(path, skip_analysis=True, output=output)

        self.assertEqual(stats.succeeded, 1)
        self.assertIn("truthfulness_score", output.getvalue())


class DatabaseImportTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.created_slugs: list[str] = []

    def tearDown(self):
        for slug in self.created_slugs:
            rumor = get_rumor_by_slug(self.db, slug)
            if rumor:
                analysis = get_analysis_by_rumor_id(self.db, rumor.id)
                if analysis:
                    self.db.delete(analysis)
                    self.db.commit()
                delete_rumor(self.db, rumor.id)
        self.db.close()

    def write_jsonl(self, rows: list[object]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl", encoding="utf-8")
        with handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_slug_conflict_appends_hash(self):
        title = "duplicate-title"
        sample_a = {"raw_text": "Officials debunked this first test sample.", "title": title}
        sample_b = {"raw_text": "Officials debunked this second test sample.", "title": title}
        path = self.write_jsonl([sample_a, sample_b])
        response = StructuredRumorAnalysis(
            title=title,
            summary=None,
            rumor_content="ignored",
            truth_content=None,
            status=RumorStatus.FAKE,
            tags=None,
            source_urls=None,
            analysis_summary="test",
            truthfulness_score=0.8,
            evidence="Officials debunked it.",
        )

        stats = import_jsonl_file(path, analyzer=FakeAnalyzer([response, response]))

        self.assertEqual(stats.succeeded, 2)
        first_slug = slugify(title)
        second_slug = f"{first_slug}-{hashlib.sha1(sample_b['raw_text'].encode('utf-8')).hexdigest()[:8]}"
        first = get_rumor_by_slug(self.db, first_slug)
        second = get_rumor_by_slug(self.db, second_slug)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.created_slugs.extend([first_slug, second_slug])

    def test_database_import_creates_rumor_and_analysis(self):
        title = f"db-integration-{uuid4().hex[:8]}"
        path = self.write_jsonl([{"raw_text": "The sample explicitly says officials debunked it.", "title": title}])
        response = StructuredRumorAnalysis(
            title=title,
            summary="summary",
            rumor_content="ignored",
            truth_content="explanation",
            status=RumorStatus.FAKE,
            tags=["test"],
            source_urls=["https://example.com"],
            analysis_summary="analysis-summary",
            truthfulness_score=0.9,
            evidence="Officials debunked it.",
        )

        stats = import_jsonl_file(path, analyzer=FakeAnalyzer([response]))

        self.assertEqual(stats.succeeded, 1)
        rumor = get_rumor_by_slug(self.db, slugify(title))
        self.assertIsNotNone(rumor)
        self.created_slugs.append(rumor.slug)
        analysis = get_analysis_by_rumor_id(self.db, rumor.id)
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.summary, "analysis-summary")


if __name__ == "__main__":
    unittest.main()
