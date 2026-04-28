"""Stage 1: Xiaohongshu (RED) note search collector via MCP.

Connects to a local xiaohongshu-mcp service, searches notes by keyword,
fetches detail for each result, and writes raw JSONL to
``data/staging/raw/``.  No database interaction happens here.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from src.config import settings

logger = logging.getLogger(__name__)

DEFAULT_STAGING_DIR = Path("data/staging/raw")

MCP_PROTOCOL_VERSION = "2024-11-05"


class XhsLoginError(RuntimeError):
    """Raised when the MCP service reports the account is not logged in."""


# ── MCP low-level helpers ────────────────────────────────────────────────────

def _base_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Content-Type": "application/json",
    }


def _mcp_post(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    timeout: int = 60,
) -> dict[str, Any]:
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _mcp_init(url: str) -> tuple[dict[str, str], str]:
    """Perform MCP initialize handshake, return (headers_with_session, session_id)."""
    headers = _base_headers()
    body = {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "rumor-agent-xhs", "version": "0.1.0"},
        },
    }
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    session_id = resp.headers["Mcp-Session-Id"]
    headers["Mcp-Session-Id"] = session_id
    return headers, session_id


def _mcp_tool_call(
    url: str,
    headers: dict[str, str],
    tool_name: str,
    arguments: dict[str, Any],
    *,
    request_id: str = "call",
    timeout: int = 60,
) -> str:
    """Call an MCP tool and return the text content from the first content block."""
    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    data = _mcp_post(url, headers, body, timeout=timeout)
    return data.get("result", {}).get("content", [{}])[0].get("text", "")


# ── Business-level helpers ───────────────────────────────────────────────────

def _check_login(url: str, headers: dict[str, str]) -> None:
    text = _mcp_tool_call(url, headers, "check_login_status", {}, timeout=30)
    if "未登录" in text or "not logged" in text.lower():
        raise XhsLoginError(
            "小红书未登录，请先在浏览器中扫码登录后再运行采集"
        )
    logger.info("XHS login check passed")


def _search_feeds(
    url: str,
    headers: dict[str, str],
    keyword: str,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    arguments: dict[str, Any] = {"keyword": keyword}
    if filters:
        arguments["filters"] = filters
    text = _mcp_tool_call(
        url, headers, "search_feeds", arguments,
        request_id="search", timeout=60,
    )
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        logger.warning("search_feeds returned non-JSON: %s", text[:200])
        return []
    return payload.get("feeds", [])


def _fetch_detail(
    url: str,
    headers: dict[str, str],
    feed_id: str,
    xsec_token: str,
    *,
    max_retries: int | None = None,
    retry_delay_range: tuple[float, float] | None = None,
) -> str:
    """Fetch note detail with retry logic. Returns desc text or empty string."""
    retries = max_retries if max_retries is not None else settings.XHS_MAX_RETRIES
    delay_range = retry_delay_range or settings.XHS_RETRY_DELAY_RANGE

    for attempt in range(1, retries + 1):
        try:
            text = _mcp_tool_call(
                url, headers, "get_feed_detail",
                {"feed_id": feed_id, "xsec_token": xsec_token, "load_all_comments": False},
                request_id=f"detail-{feed_id}-{attempt}",
                timeout=90,
            )
        except Exception as exc:
            logger.warning("[%s] detail request failed (attempt %d/%d): %s", feed_id, attempt, retries, exc)
            time.sleep(random.uniform(*delay_range))
            continue

        if "Page Isn't Available" in text or "笔记不可访问" in text:
            logger.warning("[%s] 笔记不可访问 (attempt %d/%d)", feed_id, attempt, retries)
            time.sleep(random.uniform(*delay_range))
            continue

        try:
            obj = json.loads(text) if text else {}
        except json.JSONDecodeError:
            obj = {}

        desc = (
            obj.get("data", {}).get("note", {}).get("desc", "")
            or obj.get("data", {}).get("note", {}).get("title", "")
        )
        if desc:
            return desc

        logger.debug("[%s] empty desc (attempt %d/%d)", feed_id, attempt, retries)
        if attempt < retries:
            time.sleep(random.uniform(*delay_range))

    return ""


def build_note_url(note_id: str, xsec_token: str) -> str:
    if not note_id or not xsec_token:
        return ""
    return (
        f"https://www.xiaohongshu.com/explore/{note_id}"
        f"?xsec_token={xsec_token}&xsec_source=pc_search"
    )


def parse_feed(
    feed: dict[str, Any],
    *,
    keyword: str,
    rank_offset: int,
) -> dict[str, Any]:
    """Convert a single search_feeds item into a raw JSONL row."""
    note_card = feed.get("noteCard", {})
    user = note_card.get("user", {})
    interact = note_card.get("interactInfo", {})
    note_id = feed.get("id", "")
    xsec_token = feed.get("xsecToken", "")

    return {
        "keyword": keyword,
        "title": note_card.get("displayTitle", ""),
        "description": "",
        "source_url": build_note_url(note_id, xsec_token),
        "note_id": note_id,
        "xsec_token": xsec_token,
        "author": user.get("nickname") or user.get("nickName", ""),
        "rank_meta": {
            "rank_offset": rank_offset,
            "liked_count": interact.get("likedCount", "0"),
            "comment_count": interact.get("commentCount", "0"),
        },
    }


# ── Public API ───────────────────────────────────────────────────────────────

def collect_xhs(
    keyword: str,
    *,
    filters: dict[str, str] | None = None,
    max_items: int | None = None,
    staging_dir: Path | None = None,
) -> Path:
    """Run a single XHS collection pass and write raw JSONL.

    Returns the path to the written file.
    """
    mcp_url = settings.XHS_MCP_URL
    items_limit = max_items if max_items is not None else settings.XHS_MAX_ITEMS
    delay_range = settings.XHS_DELAY_RANGE

    logger.info(
        "XHS collect: keyword=%r filters=%s max_items=%d delay=%.1f~%.1f",
        keyword, filters, items_limit, delay_range[0], delay_range[1],
    )

    headers, session_id = _mcp_init(mcp_url)
    logger.info("MCP session established: %s", session_id)

    _check_login(mcp_url, headers)

    feeds = _search_feeds(mcp_url, headers, keyword, filters)
    feeds = feeds[:items_limit]
    logger.info("search_feeds returned %d items (capped to %d)", len(feeds), items_limit)

    rows: list[dict[str, Any]] = []

    for idx, feed in enumerate(feeds):
        row = parse_feed(feed, keyword=keyword, rank_offset=idx)

        if row["note_id"] and row.get("xsec_token"):
            desc = _fetch_detail(mcp_url, headers, row["note_id"], row["xsec_token"])
            row["description"] = desc
            time.sleep(random.uniform(*delay_range))

        rows.append(row)

    out_dir = staging_dir or DEFAULT_STAGING_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"xhs_{stamp}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            row.pop("xsec_token", None)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    logger.info("XHS collection done: %d rows → %s", len(rows), out_path)
    return out_path
