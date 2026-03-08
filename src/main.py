from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, TextIO
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from src.analyzer.analyzer import (
    analyze_sample,
    build_preview_analysis,
    hash_suffix,
    slugify,
    to_rumor_create,
)
from src.config import settings
from src.db.base import SessionLocal
from src.db.crud import create_analysis_result, create_rumor, get_analysis_by_rumor_id, get_rumor_by_slug
from src.db.models import Rumor
from src.db.schemas import AnalysisResultCreate, RumorSampleIn


@dataclass
class ImportStats:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    duplicates: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rumor Agent CLI")
    parser.add_argument("--import-jsonl", type=Path, help="Import rumor samples from a JSONL file")
    parser.add_argument("--limit", type=int, help="Maximum number of JSONL rows to process")
    parser.add_argument("--dry-run", action="store_true", help="Run the pipeline without writing to the database")
    parser.add_argument("--model", help="Override the configured LLM model")
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Parse and preview JSONL input without calling the LLM or writing to the database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.import_jsonl:
        stats = import_jsonl_file(
            args.import_jsonl,
            limit=args.limit,
            dry_run=args.dry_run,
            model=args.model,
            skip_analysis=args.skip_analysis,
        )
        print(
            f"Import finished. processed={stats.processed} "
            f"succeeded={stats.succeeded} failed={stats.failed} duplicates={stats.duplicates}"
        )
        return 0 if stats.failed == 0 else 1

    print("Network Rumor Agent initialized.")
    print("Database models loaded.")
    db = SessionLocal()
    try:
        count = db.query(Rumor).count()
        print(f"Successfully connected to database. Current rumors count: {count}")
        return 0
    except Exception as exc:
        print(f"Database connection failed (expected if not configured): {exc}")
        return 1
    finally:
        db.close()


def import_jsonl_file(
    path: Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    model: str | None = None,
    skip_analysis: bool = False,
    output: TextIO | None = None,
    analyzer=None,
) -> ImportStats:
    stream = output or sys.stdout
    stats = ImportStats()
    db = None if skip_analysis else SessionLocal()

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                if limit is not None and stats.processed >= limit:
                    break
                if not raw_line.strip():
                    continue

                stats.processed += 1
                created_rumor_id = None

                try:
                    sample = RumorSampleIn.model_validate_json(raw_line)
                    if skip_analysis:
                        print_preview(stream, line_no, build_preview_analysis(sample))
                        stats.succeeded += 1
                        continue

                    structured = analyze_sample(sample, model=model, client=analyzer)
                    slug = resolve_slug(db, structured.title, sample.raw_text)
                    if slug is None:
                        stats.duplicates += 1
                        print(f"Line {line_no}: duplicate rumor skipped", file=stream)
                        continue

                    rumor_data = to_rumor_create(
                        structured,
                        slug=slug,
                        is_published=sample.is_published,
                    )
                    analysis_data = AnalysisResultCreate(
                        rumor_id=UUID(int=0),
                        summary=structured.analysis_summary,
                        truthfulness_score=structured.truthfulness_score,
                        evidence=structured.evidence,
                        model_name=model or settings.LLM_MODEL,
                    )

                    if dry_run:
                        print_preview(
                            stream,
                            line_no,
                            {
                                "rumor": rumor_data.model_dump(mode="json"),
                                "analysis": {
                                    **analysis_data.model_dump(mode="json", exclude={"rumor_id"}),
                                    "status": structured.status.value,
                                },
                            },
                        )
                        stats.succeeded += 1
                        continue

                    rumor = create_rumor(db, rumor_data)
                    created_rumor_id = rumor.id
                    create_analysis_result(
                        db,
                        analysis_data.model_copy(update={"rumor_id": rumor.id}),
                    )
                    stats.succeeded += 1
                except ValidationError as exc:
                    stats.failed += 1
                    print(f"Line {line_no}: {exc}", file=stream)
                except Exception as exc:
                    stats.failed += 1
                    print(f"Line {line_no}: {exc}", file=stream)
                    if db is not None and created_rumor_id is not None:
                        cleanup_rumor_bundle(db, created_rumor_id)
    finally:
        if db is not None:
            db.close()

    return stats


def print_preview(stream: TextIO, line_no: int, payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(f"Line {line_no}: {json.dumps(payload, ensure_ascii=False)}", file=stream)


def resolve_slug(db, title: str, raw_text: str) -> str | None:
    base_slug = slugify(title)
    if get_rumor_by_slug(db, base_slug) is None:
        return base_slug

    deduped_slug = f"{base_slug}-{hash_suffix(raw_text)}"
    if get_rumor_by_slug(db, deduped_slug) is None:
        return deduped_slug
    return None


def cleanup_rumor_bundle(db, rumor_id) -> None:
    analysis = get_analysis_by_rumor_id(db, rumor_id)
    if analysis is not None:
        db.delete(analysis)
        db.commit()
    rumor = db.get(Rumor, rumor_id)
    if rumor is not None:
        db.delete(rumor)
        db.commit()


if __name__ == "__main__":
    raise SystemExit(main())
