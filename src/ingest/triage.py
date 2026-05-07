"""Stage 2: LLM-based triage of raw search results.

Reads one or more raw JSONL files produced by Stage 1, applies minimal
rule-based filtering, then asks an LLM to consolidate the surviving items
into a list of *controversy events*.  Each event groups related posts
that discuss the same claim or dispute.

Output: a candidate JSONL where each line is one controversy event ready
for database import.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.llm.client import chat as llm_chat

logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path("data/staging/raw")
DEFAULT_CANDIDATE_DIR = Path("data/staging/candidates")

TRIAGE_PROMPT_TEMPLATE = """\
你是一个专业的网络舆情分析助手。

任务背景：
- 当前搜索关键词：{keyword}
- 输入是一批社交媒体搜索结果，字段包括：title、description、url、author、rank_meta、comments。
- comments 是该帖子评论区前 N 条高赞评论，是辅助信号；评论中的二次质疑、相互冲突的叙述也算争议线索，但要分清楚是网友质疑还是无关八卦/调侃。
- 你的任务是识别"谣言、争议、未经证实说法、有明显分歧观点"的内容，并按同一争议点合并。

识别规则：
1. 识别"应纳入争议"的内容：
   - 明确指控、质疑、爆料、维权、投诉、质疑官方说法；
   - 对质量/安全/性能/价格/宣传/合规/售后提出争议；
   - 对同一事件出现相互冲突或对立叙事；
   - 帖子本身平淡但评论区集中出现高赞质疑，也可纳入。
2. 过滤"非争议"内容：
   - 普通开箱、体验、教程、娱乐内容；
   - 与关键词弱相关或几乎无信息量的内容；
   - 评论区只有调侃 / 表情包 / 与关键词无关的灌水。
3. 可参考 author 与 rank_meta 判断代表性，优先保留更有传播度或信息密度的来源。
4. 不做真假裁决，只客观归纳争议点。

输出要求：
- 返回 JSON 数组，元素为对象，字段固定为：
  - "title": 争议点标题（一句话，短而具体）
  - "content": 争议摘要（2-5 句，必须保留核心主张，不要空泛表述）
  - "source_urls": 来源 URL 数组（只使用输入中出现过的 URL）
  - "controversy_type": 仅能为以下 8 类之一：
    "安全" / "质量" / "性能" / "价格" / "营销宣传" / "合规法律" / "售后服务" / "其他"
- 若没有争议内容，返回 []。
- 仅返回 JSON，不要 markdown 代码块或额外解释文本。
- content 写作风格要求：
  - 不要使用"有视频称/有内容称/有帖子称"等空泛主语。
  - 优先使用"平台 + 作者"作为主语并直接归因，例如：
    - "小红书用户<author>称……"
    - "Bilibili用户<author>称……"
  - 平台可根据 URL 域名判断（`xiaohongshu.com` => 小红书；`bilibili.com` => Bilibili）。
  - 若 author 为空，再退化为"某小红书用户/某Bilibili用户"。
  - 若主要争议来自评论区，可写"评论区集中质疑……"。

示例（仅示意）：
输入中若出现"产品A被指宣传参数与实测不符""商家疑似虚假宣传"；
可输出 controversy_type 为"营销宣传"，而不是"其他"。
"""

ALLOWED_CONTROVERSY_TYPES = {
    "安全",
    "质量",
    "性能",
    "价格",
    "营销宣传",
    "合规法律",
    "售后服务",
    "其他",
}

CONTROVERSY_TYPE_ALIASES = {
    "营销": "营销宣传",
    "宣传": "营销宣传",
    "合规": "合规法律",
    "法律": "合规法律",
    "法务": "合规法律",
    "售后": "售后服务",
}


# ── Minimal rule-based pre-filter ────────────────────────────────────────────

_MIN_TEXT_LENGTH = 8


def _is_noise(record: dict[str, Any]) -> bool:
    """Drop records with empty or extremely short text."""
    title = (record.get("title") or "").strip()
    desc = (record.get("description") or "").strip()
    if not title and not desc:
        return True
    if len(title + desc) < _MIN_TEXT_LENGTH:
        return True
    return False


# ── LLM helpers ──────────────────────────────────────────────────────────────

def _get_url(record: dict[str, Any]) -> str:
    return record.get("arcurl") or record.get("source_url") or ""


def _get_raw_id(record: dict[str, Any]) -> str:
    return record.get("bvid") or record.get("note_id") or record.get("id") or ""


def _platform_from_record(record: dict[str, Any]) -> str:
    url = _get_url(record)
    if record.get("bvid") or "bilibili.com" in url:
        return "bilibili"
    if record.get("note_id") or "xiaohongshu.com" in url:
        return "xhs"
    return ""


def _source_ref(record: dict[str, Any]) -> dict[str, str]:
    ref = {"url": _get_url(record)}
    raw_id = _get_raw_id(record)
    if raw_id:
        ref["raw_id"] = raw_id
    platform = _platform_from_record(record)
    if platform:
        ref["platform"] = platform
    return ref


def _build_source_lookup(records: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for record in records:
        url = _get_url(record)
        if url and url not in lookup:
            lookup[url] = _source_ref(record)
    return lookup


def _format_comments(comments: Any) -> list[str]:
    if not isinstance(comments, list):
        return []
    out: list[str] = []
    for c in comments:
        if not isinstance(c, dict):
            continue
        text = (c.get("text") or "").strip()
        if not text:
            continue
        author = (c.get("author") or "").strip() or "匿名"
        like = c.get("like") or 0
        out.append(f"{author}(👍{like}): {text}")
    return out


def _build_llm_input(records: list[dict[str, Any]], keyword: str = "") -> str:
    items = []
    for r in records:
        items.append({
            "title": r.get("title", ""),
            "description": r.get("description", ""),
            "url": _get_url(r),
            "author": r.get("author", ""),
            "rank_meta": r.get("rank_meta", {}),
            "comments": _format_comments(r.get("comments")),
        })
    payload = {
        "search_keyword": keyword,
        "items": items,
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_triage_prompt(keyword: str) -> str:
    return TRIAGE_PROMPT_TEMPLATE.format(keyword=keyword or "（未提供）")


def _normalize_controversy_type(raw_type: Any) -> str:
    value = (str(raw_type or "其他")).strip()
    value = CONTROVERSY_TYPE_ALIASES.get(value, value)
    if value not in ALLOWED_CONTROVERSY_TYPES:
        return "其他"
    return value


def _parse_events(
    raw_response: str,
    *,
    allowed_urls: set[str] | None = None,
    source_lookup: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Parse the LLM JSON array response into a list of controversy events.

    When ``allowed_urls`` is provided, every event's ``source_urls`` is filtered
    to keep only URLs that appeared in the raw input pool — drops LLM-fabricated
    URLs. Events that end up with no allowed sources are dropped entirely. When
    ``source_lookup`` is provided, matched raw item IDs are copied into
    ``source_refs`` for candidate-level traceability.
    """
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    results = json.loads(text)
    if not isinstance(results, list):
        raise ValueError("Expected JSON array from LLM")

    events: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue

        urls = [u for u in (item.get("source_urls") or []) if isinstance(u, str)]
        if allowed_urls is not None:
            original_count = len(urls)
            urls = [u for u in urls if u in allowed_urls]
            dropped = original_count - len(urls)
            if dropped:
                logger.warning(
                    "Triage: dropped %d hallucinated URL(s) from event %r",
                    dropped, title[:40],
                )
            if not urls:
                logger.warning(
                    "Triage: event %r has no allowed source_urls after filtering, dropping",
                    title[:40],
                )
                continue

        event = {
            "title": title,
            "content": (item.get("content") or "").strip(),
            "source_urls": urls,
            "controversy_type": _normalize_controversy_type(item.get("controversy_type")),
        }
        if source_lookup is not None:
            refs = [source_lookup[u] for u in urls if u in source_lookup]
            if refs:
                event["source_refs"] = refs
        events.append(event)
    return events


# ── Public API ────────────────────────────────────────────────────────────────

def triage_raw_jsonl(
    raw_paths: list[Path] | Path,
    *,
    candidate_dir: Path | None = None,
) -> Path:
    """Read raw JSONL file(s), ask LLM to extract controversy events.

    Accepts a single Path or a list of Paths.  All records from all files
    are pooled together and sent to the LLM in one call.

    Returns path to the candidate JSONL (one line per event).
    """
    if isinstance(raw_paths, Path):
        raw_paths = [raw_paths]

    out_dir = candidate_dir or DEFAULT_CANDIDATE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    all_records: list[dict[str, Any]] = []
    keywords: set[str] = set()
    for path in raw_paths:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                kw = rec.get("keyword", "")
                if kw:
                    keywords.add(kw)
                all_records.append(rec)

    noise_count = 0
    surviving: list[dict[str, Any]] = []
    for rec in all_records:
        if _is_noise(rec):
            noise_count += 1
        else:
            surviving.append(rec)

    logger.info(
        "Triage: %d total records from %d file(s), %d noise dropped, %d to LLM",
        len(all_records), len(raw_paths), noise_count, len(surviving),
    )

    if not surviving:
        logger.warning("No records survived filtering, skipping LLM call")
        events: list[dict[str, Any]] = []
    else:
        keyword_for_prompt = "、".join(sorted(keywords)) if keywords else ""
        llm_input = _build_llm_input(surviving, keyword=keyword_for_prompt)
        llm_raw = llm_chat(_build_triage_prompt(keyword_for_prompt), llm_input)
        # Build the allowed-URL set from the raw inputs so the LLM cannot
        # fabricate sources that were never seen.
        allowed_urls = {url for url in (_get_url(r) for r in surviving) if url}
        events = _parse_events(
            llm_raw,
            allowed_urls=allowed_urls,
            source_lookup=_build_source_lookup(surviving),
        )

    keyword_tag = list(keywords)[0] if len(keywords) == 1 else None
    for ev in events:
        if keyword_tag:
            ev["keyword"] = keyword_tag

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"candidate_{stamp}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    logger.info("Triage done: %d controversy events → %s", len(events), out_path)
    return out_path
