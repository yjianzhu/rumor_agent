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
from src.db.crud import create_analysis_result, create_rumor, find_similar_rumor, get_rumor_by_slug, get_rumor_by_slug_hash
from src.db.models import Rumor, RumorStatus
from src.db.schemas import AnalysisResultCreate, RumorCreate, RumorDirectIn
from src.embedding import get_embedding
from src.ingest.readers import read_fused_json_record, read_markdown_sample


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

    # ── Ingest pipeline commands ──────────────────────────────────────────
    group.add_argument(
        "--collect-bili",
        nargs="?",
        const="",
        default=None,
        metavar="KEYWORD",
        help="Stage 1: Collect Bilibili search results → raw JSONL. "
             "Omit KEYWORD to use [collect].keywords from config.",
    )
    group.add_argument(
        "--collect-xhs",
        nargs="?",
        const="",
        default=None,
        metavar="KEYWORD",
        help="Stage 1: Collect Xiaohongshu notes via MCP → raw JSONL. "
             "Omit KEYWORD to use [collect].keywords from config.",
    )
    group.add_argument(
        "--triage-jsonl",
        type=Path,
        metavar="FILE",
        nargs="+",
        help="Stage 2: LLM triage of raw JSONL(s) → candidate JSONL (controversy events)",
    )
    group.add_argument(
        "--import-candidate-jsonl",
        type=Path,
        metavar="FILE",
        help="Import candidate JSONL (controversy events) into database as DUBIOUS rumors",
    )
    group.add_argument(
        "--fuse-jsonl",
        type=Path,
        metavar="FILE",
        nargs="+",
        help="(Legacy) Stage 3: Fuse candidate JSONL(s) → fused JSONL",
    )
    group.add_argument(
        "--import-fused-jsonl",
        type=Path,
        metavar="FILE",
        help="(Legacy) Stage 4: Import fused JSONL into database via LLM analysis",
    )

    parser.add_argument("--limit", type=int, help="Maximum number of records to process")
    parser.add_argument("--dry-run", action="store_true", help="Parse and preview without writing to the database")
    parser.add_argument("--model", help="Override the configured LLM model")

    # Bilibili collection options
    parser.add_argument("--bili-order", default="totalrank",
                        choices=["totalrank", "click", "pubdate", "dm", "stow", "scores"],
                        help="Sort order for --collect-bili (default: totalrank)")
    parser.add_argument("--bili-pages", type=int, default=1, help="Max pages to fetch (default: 1)")
    parser.add_argument("--bili-min-play", type=int, default=None,
                        help="Min play count filter for --collect-bili (default: from config, 100)")
    parser.add_argument("--bili-time-start", type=str, help="Start date YYYY-MM-DD for --collect-bili")
    parser.add_argument("--bili-time-end", type=str, help="End date YYYY-MM-DD for --collect-bili")

    # Xiaohongshu collection options
    parser.add_argument("--xhs-sort-by", default="最多评论",
                        choices=["综合", "最新", "最多点赞", "最多评论", "最多收藏"],
                        help="Sort order for --collect-xhs (default: 综合)")
    parser.add_argument("--xhs-publish-time", default="一天内",
                        choices=["不限", "一天内", "一周内", "半年内"],
                        help="Publish time filter for --collect-xhs (default: 一天内)")
    parser.add_argument("--xhs-note-type", default="不限",
                        choices=["不限", "视频", "图文"],
                        help="Note type filter for --collect-xhs (default: 不限)")
    parser.add_argument("--xhs-max-items", type=int, help="Max items to fetch (overrides config)")
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

    if args.collect_bili is not None:
        keywords = _resolve_keywords(args.collect_bili)
        from datetime import date, timedelta
        from src.ingest.bilibili_collector import collect_bilibili
        today = date.today()
        yesterday = today - timedelta(days=1)
        outputs: list[Path] = []
        for kw in keywords:
            logger.info("Collecting Bilibili: keyword=%s", kw)
            out = collect_bilibili(
                kw,
                order=args.bili_order,
                time_start=args.bili_time_start or yesterday.strftime("%Y-%m-%d"),
                time_end=args.bili_time_end or today.strftime("%Y-%m-%d"),
                max_pages=args.bili_pages,
                min_play=args.bili_min_play,
            )
            outputs.append(out)
            logger.info("  → %s", out)
        logger.info("Stage 1 done: %d keyword(s), files: %s", len(outputs), outputs)
        return 0

    if args.collect_xhs is not None:
        keywords = _resolve_keywords(args.collect_xhs)
        from src.ingest.xhs_collector import collect_xhs
        filters: dict[str, str] = {}
        if args.xhs_sort_by != "综合":
            filters["sort_by"] = args.xhs_sort_by
        if args.xhs_publish_time != "不限":
            filters["publish_time"] = args.xhs_publish_time
        if args.xhs_note_type != "不限":
            filters["note_type"] = args.xhs_note_type
        outputs: list[Path] = []
        for kw in keywords:
            logger.info("Collecting XHS: keyword=%s", kw)
            out = collect_xhs(
                kw,
                filters=filters or None,
                max_items=args.xhs_max_items,
            )
            outputs.append(out)
            logger.info("  → %s", out)
        logger.info("Stage 1 done: %d keyword(s), files: %s", len(outputs), outputs)
        return 0

    if args.triage_jsonl:
        from src.ingest.triage import triage_raw_jsonl
        paths = args.triage_jsonl if isinstance(args.triage_jsonl, list) else [args.triage_jsonl]
        out = triage_raw_jsonl(paths)
        logger.info("Stage 2 done → %s", out)
        return 0

    if args.import_candidate_jsonl:
        stats = import_candidate_jsonl(
            args.import_candidate_jsonl,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        logger.info(
            "Candidate import done. processed=%d succeeded=%d failed=%d duplicates=%d",
            stats.processed, stats.succeeded, stats.failed, stats.duplicates,
        )
        return 0 if stats.failed == 0 else 1

    if args.fuse_jsonl:
        from src.ingest.fusion import fuse_candidates
        paths = args.fuse_jsonl if isinstance(args.fuse_jsonl, list) else [args.fuse_jsonl]
        out = fuse_candidates(paths)
        logger.info("Stage 3 done → %s", out)
        return 0

    if args.import_fused_jsonl:
        stats = import_fused_jsonl(
            args.import_fused_jsonl,
            limit=args.limit,
            dry_run=args.dry_run,
            model=args.model,
        )
        logger.info(
            "Stage 4 done. processed=%d succeeded=%d failed=%d duplicates=%d",
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
                        resolved = _resolve_slug(db, slug, dedup_content, emb)
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


def _resolve_slug(
    db,
    base_slug: str,
    content: str,
    embedding: list[float] | None = None,
    *,
    always_hash: bool = False,
) -> str | None:
    """Two-phase dedup: slug/hash check first, then semantic similarity.

    Args:
        base_slug: The desired slug (already slugified).
        content: Raw text used to derive the content hash.
        embedding: Optional embedding vector for semantic dedup.
        always_hash: When True (MD / fused path), always append the content
            hash to the slug and check for hash collisions only.  When False
            (direct JSONL path), try ``base_slug`` as-is first and only fall
            back to a hash-suffixed slug on collision.
    """
    content_hash = hash_suffix(content)
    hashed_slug = f"{base_slug}-{content_hash}"

    if always_hash:
        # Hash-suffix path: slug always ends with content hash, so a matching
        # hash means identical content → skip.
        if get_rumor_by_slug_hash(db, content_hash) is not None:
            return None
        candidate = hashed_slug
    else:
        # Direct path: prefer the explicit slug, fall back to hashed slug.
        existing = get_rumor_by_slug(db, base_slug)
        if existing is None:
            candidate = base_slug
        else:
            existing_content = f"{existing.title}\n{existing.rumor_content or ''}"
            if hash_suffix(existing_content) == content_hash:
                return None
            if get_rumor_by_slug(db, hashed_slug) is not None:
                return None
            candidate = hashed_slug

    # Pass 2: semantic similarity
    if embedding is not None:
        similar = find_similar_rumor(db, embedding)
        if similar is not None:
            logger.info("Semantic duplicate found: slug=%s similar_to=%s", base_slug, similar.slug)
            return None

    return candidate


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
        sample, media_items, raw_text = read_markdown_sample(path)

        if dry_run:
            structured = analyze_sample(sample, model=model, client=analyzer)
            content_hash = hash_suffix(raw_text)
            slug = f"{slugify(structured.title)}-{content_hash}"
            print_preview(stream, 1, {
                "slug": slug,
                "rumor": to_rumor_create(structured, slug=slug, is_published=False, media_files=media_items).model_dump(mode="json"),
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
        slug = _resolve_slug(db, slugify(structured.title), raw_text, emb, always_hash=True)
        if slug is None:
            stats.duplicates = 1
            logger.warning("Duplicate rumor skipped for: %s", path.name)
            return stats

        rumor_data = to_rumor_create(structured, slug=slug, is_published=False, media_files=media_items)
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


# ─── Fused JSONL import (Stage 4) ─────────────────────────────────────────────

def import_fused_jsonl(
    path: Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    model: str | None = None,
    output: TextIO | None = None,
    analyzer=None,
) -> ImportStats:
    """Read a fused JSONL file, run LLM analysis, and import to the database."""
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
                    sample, raw_text = read_fused_json_record(raw_line)

                    if dry_run:
                        structured = analyze_sample(sample, model=model, client=analyzer)
                        content_hash = hash_suffix(raw_text)
                        slug = f"{slugify(structured.title)}-{content_hash}"
                        print_preview(stream, line_no, {
                            "slug": slug,
                            "rumor": to_rumor_create(
                                structured, slug=slug, is_published=False,
                            ).model_dump(mode="json"),
                            "analysis": {
                                "analysis_summary": structured.analysis_summary,
                                "truthfulness_score": structured.truthfulness_score,
                                "evidence": structured.evidence,
                            },
                        })
                        stats.succeeded += 1
                        continue

                    structured = analyze_sample(sample, model=model, client=analyzer)
                    emb = _safe_get_embedding(raw_text)
                    slug = _resolve_slug(db, slugify(structured.title), raw_text, emb, always_hash=True)
                    if slug is None:
                        stats.duplicates += 1
                        logger.warning("Line %d: duplicate rumor skipped", line_no)
                        continue

                    rumor_data = to_rumor_create(
                        structured, slug=slug, is_published=False,
                    )
                    savepoint = db.begin_nested()
                    try:
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
                        savepoint.commit()
                        pending_count += 1
                        stats.succeeded += 1

                        if pending_count >= settings.IMPORT_BATCH_SIZE:
                            db.commit()
                            pending_count = 0
                    except Exception:
                        savepoint.rollback()
                        raise

                except Exception as exc:
                    stats.failed += 1
                    logger.error("Line %d: %s", line_no, exc)

            if db is not None and pending_count > 0:
                db.commit()
    finally:
        if db is not None:
            db.close()

    return stats


# ─── Candidate JSONL import (no LLM analysis, just extract+store) ────────────

def import_candidate_jsonl(
    path: Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    output: TextIO | None = None,
) -> ImportStats:
    """Import controversy events from candidate JSONL into the database.

    Each line is a controversy event produced by triage (LLM归纳).
    Maps directly to a Rumor row with status=DUBIOUS, no analysis_results.
    """
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
                    record = json.loads(raw_line)
                    title = record.get("title", "").strip()
                    content = record.get("content", "").strip()
                    source_urls = record.get("source_urls") or []
                    controversy_type = record.get("controversy_type", "其他").strip()
                    keyword = record.get("keyword", "").strip()

                    if not title:
                        stats.failed += 1
                        logger.warning("Line %d: empty title, skipped", line_no)
                        continue

                    tags = [t for t in [keyword, controversy_type] if t]
                    slug = slugify(title)
                    dedup_content = f"{title}\n{content}"

                    if dry_run:
                        preview = {
                            "title": title,
                            "slug": slug,
                            "summary": content,
                            "tags": tags,
                            "source_urls": source_urls,
                            "status": "DUBIOUS",
                        }
                        print_preview(stream, line_no, preview)
                        stats.succeeded += 1
                        continue

                    emb = _safe_get_embedding(dedup_content)
                    resolved = _resolve_slug(db, slug, dedup_content, emb, always_hash=True)
                    if resolved is None:
                        stats.duplicates += 1
                        logger.info("Line %d: duplicate skipped (slug=%s)", line_no, slug)
                        continue

                    rumor_data = RumorCreate(
                        title=title,
                        slug=resolved,
                        summary=content,
                        rumor_content=content,
                        truth_content=None,
                        status=RumorStatus.DUBIOUS,
                        tags=tags or None,
                        source_urls=source_urls or None,
                        is_published=False,
                    )

                    savepoint = db.begin_nested()
                    try:
                        rumor = create_rumor(db, rumor_data)
                        if emb is not None:
                            rumor.embedding = emb
                        savepoint.commit()
                        pending_count += 1
                        stats.succeeded += 1

                        if pending_count >= settings.IMPORT_BATCH_SIZE:
                            db.commit()
                            pending_count = 0
                    except Exception:
                        savepoint.rollback()
                        raise

                except Exception as exc:
                    stats.failed += 1
                    logger.error("Line %d: %s", line_no, exc)

            if db is not None and pending_count > 0:
                db.commit()
    finally:
        if db is not None:
            db.close()

    return stats


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_keywords(cli_value: str) -> list[str]:
    """Return keyword list from CLI arg or config.

    - Non-empty string  → single keyword from CLI
    - Empty string ("")  → batch from config.COLLECT_KEYWORDS
    """
    if cli_value:
        return [cli_value]
    kws = settings.COLLECT_KEYWORDS
    if not kws:
        raise SystemExit(
            "No keyword provided and [collect].keywords is empty in config.toml"
        )
    return list(kws)


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
