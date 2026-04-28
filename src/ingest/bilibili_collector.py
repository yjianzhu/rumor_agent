"""Stage 1: Bilibili video search collector.

Fetches search results from Bilibili and writes them as raw JSONL
to ``data/staging/raw/``.  No database interaction happens here.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import logging

from bilibili_api import search
from bilibili_api.search import OrderVideo, SearchObjectType

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")

DEFAULT_STAGING_DIR = Path("data/staging/raw")


def strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def normalize_url(url: str) -> str:
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url


def _parse_items(
    payload: dict, *, keyword: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in payload.get("result") or []:
        rows.append({
            "keyword": keyword,
            "title": strip_html(item.get("title") or ""),
            "description": item.get("description") or "",
            "arcurl": normalize_url(item.get("arcurl") or ""),
            "bvid": item.get("bvid") or "",
            "rank_meta": {
                "rank_offset": item.get("rank_offset"),
                "play": item.get("play"),
                "like": item.get("like"),
                "danmaku": item.get("video_review") or item.get("danmaku"),
            },
        })
    return rows


async def _fetch_pages(
    keyword: str,
    *,
    order: OrderVideo = OrderVideo.TOTALRANK,
    time_start: str | None = None,
    time_end: str | None = None,
    max_pages: int = 1,
    page_size: int = 42,
) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        payload = await search.search_by_type(
            keyword,
            search_type=SearchObjectType.VIDEO,
            order_type=order,
            time_start=time_start,
            time_end=time_end,
            page=page,
            page_size=page_size,
        )
        rows = _parse_items(payload, keyword=keyword)
        all_rows.extend(rows)
        if not rows:
            break

    return all_rows


def collect_bilibili(
    keyword: str,
    *,
    order: str = "totalrank",
    time_start: str | None = None,
    time_end: str | None = None,
    max_pages: int = 1,
    page_size: int = 42,
    min_play: int | None = None,
    staging_dir: Path | None = None,
) -> Path:
    """Run a single collection pass and write raw JSONL.

    Returns the path to the written file.
    """
    from src.config import settings
    play_threshold = min_play if min_play is not None else settings.BILI_MIN_PLAY

    logger.info(
        "Bilibili collect: keyword=%r order=%s time=%s~%s pages=%d page_size=%d min_play=%d",
        keyword, order, time_start, time_end, max_pages, page_size, play_threshold,
    )
    order_enum = OrderVideo(order)
    rows = asyncio.run(
        _fetch_pages(
            keyword,
            order=order_enum,
            time_start=time_start,
            time_end=time_end,
            max_pages=max_pages,
            page_size=page_size,
        )
    )

    total_before = len(rows)
    if play_threshold > 0:
        rows = [r for r in rows if (r.get("rank_meta", {}).get("play") or 0) >= play_threshold]
    if total_before != len(rows):
        logger.info("Filtered by min_play=%d: %d → %d rows", play_threshold, total_before, len(rows))

    out_dir = staging_dir or DEFAULT_STAGING_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"bili_{stamp}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    logger.info("Bilibili collection done: %d rows → %s", len(rows), out_path)
    return out_path
