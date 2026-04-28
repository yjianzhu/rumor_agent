"""Stage 3: Cross-platform fusion of triaged candidates.

Reads candidate JSONL(s), normalises each record into a unified schema,
groups by event key, and emits a fused JSONL ready for database import.

Supported platforms: Bilibili, Xiaohongshu.  The ``PlatformAdapter``
protocol defines the contract for adding more platforms.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_DIR = Path("data/staging/candidates")
DEFAULT_FUSED_DIR = Path("data/staging/fused")


# ── Unified record schema ────────────────────────────────────────────────────

class UnifiedRecord:
    """Platform-agnostic record used inside the fusion layer."""

    __slots__ = (
        "platform", "title", "description", "source_url",
        "published_at", "keyword", "extra",
    )

    def __init__(
        self,
        *,
        platform: str,
        title: str,
        description: str,
        source_url: str,
        published_at: str | None = None,
        keyword: str = "",
        extra: dict[str, Any] | None = None,
    ):
        self.platform = platform
        self.title = title
        self.description = description
        self.source_url = source_url
        self.published_at = published_at
        self.keyword = keyword
        self.extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "title": self.title,
            "description": self.description,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "keyword": self.keyword,
            "extra": self.extra,
        }


# ── Platform adapter protocol ────────────────────────────────────────────────

class PlatformAdapter(Protocol):
    """Interface that each platform collector must implement."""

    def adapt(self, raw: dict[str, Any]) -> UnifiedRecord | None:
        """Convert a raw JSONL record to a UnifiedRecord, or None to skip."""
        ...


# ── Bilibili adapter ─────────────────────────────────────────────────────────

class BilibiliAdapter:
    def adapt(self, raw: dict[str, Any]) -> UnifiedRecord | None:
        if not raw.get("needs_followup"):
            return None
        return UnifiedRecord(
            platform="bilibili",
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            source_url=raw.get("arcurl", ""),
            published_at=raw.get("fetched_at"),
            keyword=raw.get("keyword", ""),
            extra={
                "bvid": raw.get("bvid", ""),
                "rank_meta": raw.get("rank_meta"),
                "followup_reason": raw.get("followup_reason", ""),
                "followup_queries": raw.get("followup_queries", []),
            },
        )


# ── Xiaohongshu adapter ──────────────────────────────────────────────────────

class XiaohongshuAdapter:
    def adapt(self, raw: dict[str, Any]) -> UnifiedRecord | None:
        if not raw.get("needs_followup"):
            return None
        return UnifiedRecord(
            platform="xiaohongshu",
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            source_url=raw.get("source_url", ""),
            published_at=raw.get("fetched_at"),
            keyword=raw.get("keyword", ""),
            extra={
                "note_id": raw.get("note_id", ""),
                "author": raw.get("author", ""),
                "rank_meta": raw.get("rank_meta"),
                "followup_reason": raw.get("followup_reason", ""),
                "followup_queries": raw.get("followup_queries", []),
            },
        )


# ── Adapter registry ─────────────────────────────────────────────────────────

_ADAPTERS: dict[str, PlatformAdapter] = {
    "bilibili": BilibiliAdapter(),
    "xiaohongshu": XiaohongshuAdapter(),
}


def get_adapter(platform: str) -> PlatformAdapter:
    adapter = _ADAPTERS.get(platform)
    if adapter is None:
        raise ValueError(f"No adapter registered for platform: {platform}")
    return adapter


# ── Event-key grouping ────────────────────────────────────────────────────────

_NOISE_RE = re.compile(r"[^\w]", re.UNICODE)
_STAMP_RE = re.compile(r"(\d{8}_\d{6})")


def _event_key(record: UnifiedRecord) -> str:
    """Derive a coarse grouping key from title text."""
    normalized = _NOISE_RE.sub("", record.title).lower()
    if len(normalized) > 30:
        normalized = normalized[:30]
    return normalized or record.source_url


def _infer_platform_from_path(path: Path) -> str:
    stem = path.stem.lower()
    if stem.endswith("_candidate"):
        stem = stem[: -len("_candidate")]
    if stem.startswith("xhs_"):
        return "xiaohongshu"
    if stem.startswith("bili_"):
        return "bilibili"
    return "bilibili"


def _infer_fetched_at_from_path(path: Path) -> str | None:
    stem = path.stem
    if stem.endswith("_candidate"):
        stem = stem[: -len("_candidate")]
    match = _STAMP_RE.search(stem)
    if not match:
        return None
    try:
        dt = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
        return dt.isoformat()
    except ValueError:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def fuse_candidates(
    candidate_paths: list[Path],
    *,
    fused_dir: Path | None = None,
) -> Path:
    """Read candidate JSONL file(s), fuse, and write output.

    Returns the path to the fused JSONL file.
    """
    out_dir = fused_dir or DEFAULT_FUSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    unified: list[UnifiedRecord] = []

    for path in candidate_paths:
        inferred_platform = _infer_platform_from_path(path)
        inferred_fetched_at = _infer_fetched_at_from_path(path)
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                platform = raw.get("platform") or inferred_platform
                if "fetched_at" not in raw and inferred_fetched_at is not None:
                    raw["fetched_at"] = inferred_fetched_at
                adapter = get_adapter(platform)
                rec = adapter.adapt(raw)
                if rec is not None:
                    unified.append(rec)

    logger.info("Fusion: %d unified records from %d file(s)", len(unified), len(candidate_paths))

    # Group by event key and pick the best representative per group
    groups: dict[str, list[UnifiedRecord]] = defaultdict(list)
    for rec in unified:
        groups[_event_key(rec)].append(rec)

    fused_records: list[dict[str, Any]] = []
    for _key, members in groups.items():
        primary = members[0]
        source_urls = list({m.source_url for m in members if m.source_url})
        platforms = list({m.platform for m in members})

        descriptions = [m.description for m in members if m.description]
        merged_desc = descriptions[0] if descriptions else ""

        fused_records.append({
            "title": primary.title,
            "description": merged_desc,
            "source_urls": source_urls,
            "platforms": platforms,
            "keyword": primary.keyword,
            "published_at": primary.published_at,
            "extra": primary.extra,
        })

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"fused_{stamp}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for rec in fused_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info("Fused %d groups → %s", len(fused_records), out_path)
    return out_path
