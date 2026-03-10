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

from src.logger import configure_logging, get_logger

logger = get_logger(__name__)

from pydantic import ValidationError

from src.analyzer.analyzer import (
    analyze_markdown,
    build_preview_analysis,
    hash_suffix,
    slugify,
    to_rumor_create,
    analyze_sample,
)
from src.config import settings
from src.db.base import SessionLocal
from src.db.crud import create_analysis_result, create_rumor, find_similar_rumor, get_rumor_by_slug
from src.db.models import Rumor
from src.db.schemas import AnalysisResultCreate, RumorCreate, RumorDirectIn, _RumorSampleIn
from src.embedding import get_embedding


@dataclass
class ImportStats:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    duplicates: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rumor Agent CLI")

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--import-jsonl",
        type=Path,
        metavar="FILE",
        help="Direct import from a structured JSONL file (no LLM required)",
    )
    group.add_argument(
        "--import-md",
        type=Path,
        metavar="FILE",
        help="Analyze a Markdown file via LLM and import to database",
    )

    parser.add_argument("--limit", type=int, help="Maximum number of records to process")
    parser.add_argument("--dry-run", action="store_true", help="Parse and preview without writing to the database")
    parser.add_argument("--model", help="Override the configured LLM model (--import-md only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)

    if args.import_jsonl:
        stats = import_jsonl_file(args.import_jsonl, limit=args.limit, dry_run=args.dry_run)
        logger.info(
            "Import finished. processed=%d succeeded=%d failed=%d duplicates=%d",
            stats.processed, stats.succeeded, stats.failed, stats.duplicates,
        )
        return 0 if stats.failed == 0 else 1

    if args.import_md:
        stats = import_md_file(args.import_md, dry_run=args.dry_run, model=args.model)
        logger.info(
            "Import finished. processed=%d succeeded=%d failed=%d duplicates=%d",
            stats.processed, stats.succeeded, stats.failed, stats.duplicates,
        )
        return 0 if stats.failed == 0 else 1

    logger.info("Network Rumor Agent initialized.")
    logger.info("Database models loaded.")
    db = SessionLocal()
    try:
        count = db.query(Rumor).count()
        logger.info("Successfully connected to database. Current rumors count: %d", count)
        return 0
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        return 1
    finally:
        db.close()


# ─── Direct JSONL import (no LLM) ────────────────────────────────────────────

def import_jsonl_file(
    path: Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    output: TextIO | None = None,
) -> ImportStats:
    """Import a structured JSONL file directly into the database (no LLM)."""
    import sys
    stream = output or sys.stdout
    stats = ImportStats()
    db = None if dry_run else SessionLocal()

    try:
        with path.open("r", encoding="utf-8") as handle:
            pending_count = 0
            for line_no, raw_line in enumerate(handle, start=1):
                if limit is not None and stats.processed >= limit:
                    break
                if not raw_line.strip():
                    continue

                stats.processed += 1

                try:
                    record = RumorDirectIn.model_validate_json(raw_line)
                    slug = record.slug or slugify(record.title)

                    if not dry_run:
                        # generate embedding once — used for both dedup and storage
                        dedup_content = f"{record.title}\n{record.rumor_content or ''}"
                        emb = _safe_get_embedding(dedup_content)
                        resolved = _resolve_slug_direct(db, slug, dedup_content, emb)
                        if resolved is None:
                            stats.duplicates += 1
                            logger.warning("Line %d: duplicate rumor skipped (slug=%s)", line_no, slug)
                            continue
                        slug = resolved

                    rumor_data = RumorCreate(
                        title=record.title,
                        slug=slug,
                        summary=record.summary,
                        rumor_content=record.rumor_content,
                        truth_content=record.truth_content,
                        status=record.status,
                        tags=record.tags,
                        media_files=record.media_files,
                        source_urls=record.source_urls,
                        is_published=record.is_published,
                    )

                    if dry_run:
                        preview: dict[str, Any] = {"rumor": rumor_data.model_dump(mode="json")}
                        if record.truthfulness_score is not None:
                            preview["analysis"] = {
                                "analysis_summary": record.analysis_summary,
                                "truthfulness_score": record.truthfulness_score,
                                "evidence": record.evidence,
                                "model_name": record.model_name,
                            }
                        print_preview(stream, line_no, preview)
                        stats.succeeded += 1
                        continue

                    savepoint = db.begin_nested()
                    try:
                        rumor = create_rumor(db, rumor_data)
                        if emb is not None:
                            rumor.embedding = emb

                        if record.truthfulness_score is not None:
                            create_analysis_result(
                                db,
                                AnalysisResultCreate(
                                    rumor_id=rumor.id,
                                    summary=record.analysis_summary,
                                    truthfulness_score=record.truthfulness_score,
                                    evidence=record.evidence,
                                    model_name=record.model_name,
                                ),
                            )

                        savepoint.commit()
                        pending_count += 1
                        stats.succeeded += 1

                        if pending_count >= settings.IMPORT_BATCH_SIZE:
                            db.commit()
                            pending_count = 0
                    except Exception:
                        savepoint.rollback()
                        raise

                except ValidationError as exc:
                    stats.failed += 1
                    logger.error("Line %d: validation error: %s", line_no, exc)
                except Exception as exc:
                    stats.failed += 1
                    logger.error("Line %d: %s", line_no, exc)

            # flush remaining
            if db is not None and pending_count > 0:
                db.commit()
    finally:
        if db is not None:
            db.close()

    return stats


def _resolve_slug_direct(db, base_slug: str, content: str, embedding: list[float] | None = None) -> str | None:
    """Two-phase dedup: hash first (free), then semantic similarity."""
    # Pass 1: exact hash match
    if get_rumor_by_slug(db, base_slug) is None:
        deduped = base_slug
    else:
        deduped = f"{base_slug}-{hash_suffix(content)}"
        if get_rumor_by_slug(db, deduped) is not None:
            return None

    # Pass 2: semantic similarity
    if embedding is not None:
        similar = find_similar_rumor(db, embedding)
        if similar is not None:
            logger.info("Semantic duplicate found: slug=%s similar_to=%s", base_slug, similar.slug)
            return None

    return deduped


# ─── Markdown import via LLM ─────────────────────────────────────────────────

def import_md_file(
    path: Path,
    *,
    dry_run: bool = False,
    model: str | None = None,
    output: TextIO | None = None,
    analyzer=None,
) -> ImportStats:
    """Read a Markdown file, analyze via LLM, and import to the database."""
    import sys
    stream = output or sys.stdout
    stats = ImportStats()
    stats.processed = 1
    db = None if dry_run else SessionLocal()

    try:
        raw_text = path.read_text(encoding="utf-8").strip()
        sample = _RumorSampleIn(raw_text=raw_text, title=path.stem)

        if dry_run:
            structured = analyze_sample(sample, model=model, client=analyzer)
            content_hash = hash_suffix(raw_text)
            slug = f"{slugify(structured.title)}-{content_hash}"
            print_preview(stream, 1, {
                "slug": slug,
                "rumor": to_rumor_create(structured, slug=slug, is_published=False).model_dump(mode="json"),
                "analysis": {
                    "analysis_summary": structured.analysis_summary,
                    "truthfulness_score": structured.truthfulness_score,
                    "evidence": structured.evidence,
                },
            })
            stats.succeeded = 1
            return stats

        structured = analyze_sample(sample, model=model, client=analyzer)
        emb = _safe_get_embedding(raw_text)
        slug = _resolve_slug_md(db, structured.title, raw_text, emb)
        if slug is None:
            stats.duplicates = 1
            logger.warning("Duplicate rumor skipped for: %s", path.name)
            return stats

        rumor_data = to_rumor_create(structured, slug=slug, is_published=False)
        rumor = create_rumor(db, rumor_data)
        if emb is not None:
            rumor.embedding = emb

        create_analysis_result(
            db,
            AnalysisResultCreate(
                rumor_id=rumor.id,
                summary=structured.analysis_summary,
                truthfulness_score=structured.truthfulness_score,
                evidence=structured.evidence,
                model_name=model or settings.LLM_MODEL,
            ),
        )
        db.commit()
        stats.succeeded = 1
        logger.info("Imported from %s → slug=%s", path.name, slug)

    except Exception as exc:
        stats.failed = 1
        logger.error("Failed to import %s: %s", path.name, exc)
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()

    return stats


def _resolve_slug_md(db, title: str, raw_text: str, embedding: list[float] | None = None) -> str | None:
    content_hash = hash_suffix(raw_text)
    # Pass 1: hash match
    existing = db.query(Rumor).filter(Rumor.slug.like(f"%-{content_hash}")).first()
    if existing is not None:
        return None
    # Pass 2: semantic similarity
    if embedding is not None:
        similar = find_similar_rumor(db, embedding)
        if similar is not None:
            logger.info("Semantic duplicate found for md import: similar_to=%s", similar.slug)
            return None
    return f"{slugify(title)}-{content_hash}"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_get_embedding(text: str) -> list[float] | None:
    try:
        return get_embedding(text)
    except Exception as exc:
        logger.warning("Embedding generation failed, skipping semantic dedup: %s", exc)
        return None


def print_preview(stream: TextIO, line_no: int, payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(f"Line {line_no}: {json.dumps(payload, ensure_ascii=False)}", file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
