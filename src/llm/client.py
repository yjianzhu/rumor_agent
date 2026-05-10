"""Unified LLM caller.

Two public entry points:

- ``chat(system, user)`` — free-text completion (used by triage).
- ``analyze_structured(sample)`` — JSON-structured rumor analysis (used by analyzer).

Both share endpoint fallback, per-endpoint tenacity retry, curl_cffi transport,
and consistent error truncation in logs.
"""

from __future__ import annotations

import json
import logging
import re

from curl_cffi import requests as curl_requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import ApiEndpoint, settings
from src.db.schemas import StructuredRumorAnalysis, _RumorSampleIn

logger = logging.getLogger(__name__)

_IMPERSONATE = "chrome136"
_TIMEOUT = 120

STRUCTURED_PROMPT = """你把历史谣言/辟谣 Markdown 案例按输入文本直接整理成可入库的结构化 JSON。

规则：
- 只对输入文本做格式化抽取、直接概括和文内整理，不做联网搜索、外部检索或事实核查。
- 严格保留输入文本中的事实点、判断依据、限定条件和结论；不要删除原文已有信息，不要省略关键段落。
- 不得发散、扩写、脑补背景、替换原文含义，不能加入输入文本之外的新事实、新判断或新解释。
- 输入中的谣言内容已经包含时间、人物、事件等基本信息；rumor_content 只整理这部分谣言主张，尽量保留原文表述和细节。
- 如果输入包含"辟谣、真相、事实核查、结论、总结"等内容，把它整理到 truth_content，并严格按以下两段结构输出（用 Markdown 二级标题 `## ` 分段，且仅保留这两个标题，不允许出现其他标题）：
    `## 辟谣与真相分析`：原文中的事实核查、依据、过程、限定条件，逐点整理；可使用列表与加粗，但不要保留原文里的"一、二、三、"或"1. 2. 3."这类章节序号编号（章节级编号一律删除；列表项可以正常用 `-` 或 `1.`）。
    `## 总结`：1-3 句陈述句，给出最终核查结论与关键限定条件，不要重复"辟谣与真相分析"里的细节，也不要出现"综上所述/总而言之"这类套话。
- 如果输入没有辟谣/真相内容，truth_content 返回 null。
- 只有输入文本明确给出结论时，status 才能是 FAKE、TRUE 或 OUTDATED；否则设为 DUBIOUS。
- truthfulness_score 表示你对“从输入文本中抽取该结论”的置信度，不是真实世界真伪概率。
- evidence 只能引用或概括输入文本中可见的依据，不得补充外部事实。
- title 要短而具体。
- summary 用一句中文陈述句直接写出核查结论本身（例：「XX 与事实不符，实际是 YY」「该说法属实」「该信息已过期」），读起来像独立结论。禁止出现"文本中""原文""文章""材料""上文""根据描述""作者提到"等指代输入材料的措辞；也不要写"摘要：""结论："等前缀。不得引入输入文本之外的信息。
- tags 提取 2-6 个简短标签。
- source_urls 只能包含输入字段或 raw_text 中明确出现的 URL。
- 返回结果必须完整匹配 schema。
- 只返回 JSON 对象，不要 markdown 代码块或额外解释。
"""


# ─── Public API ──────────────────────────────────────────────────────────────

def chat(system: str, user: str, *, model: str | None = None) -> str:
    """Free-text chat completion. Tries each configured endpoint in order."""
    return _call_with_fallback(
        lambda ep: _chat_one(ep, system, user, model=model),
        op="chat",
    )


def analyze_structured(
    sample: _RumorSampleIn,
    *,
    model: str | None = None,
) -> StructuredRumorAnalysis:
    """Run structured rumor analysis. Tries each configured endpoint in order."""
    sample = _truncate_sample(sample)
    schema_hint = json.dumps(StructuredRumorAnalysis.model_json_schema(), ensure_ascii=False)
    user_content = (
        f"JSON Schema for your response:\n{schema_hint}\n\n"
        f"Sample:\n{sample.model_dump_json()}"
    )

    raw = _call_with_fallback(
        lambda ep: _chat_one(ep, STRUCTURED_PROMPT, user_content, model=model),
        op="analyze",
    )
    return StructuredRumorAnalysis.model_validate(_parse_json(raw))


# ─── Endpoint fallback ───────────────────────────────────────────────────────

def _call_with_fallback(call_one, *, op: str) -> str:
    endpoints = settings.llm_endpoint_list
    if not endpoints:
        raise RuntimeError("No LLM endpoints configured")
    last_exc: Exception | None = None
    for i, ep in enumerate(endpoints):
        try:
            return call_one(ep)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "LLM endpoint %d (%s) failed during %s: %s",
                i, ep.api_base, op, _truncate_exc(exc),
            )
    raise RuntimeError(
        f"All {len(endpoints)} LLM endpoints failed for {op}. "
        f"Last error: {_truncate_exc(last_exc)}"
    ) from last_exc


# ─── Single-endpoint chat with tenacity retry ────────────────────────────────

@retry(
    stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)
def _chat_one(
    ep: ApiEndpoint,
    system: str,
    user: str,
    *,
    model: str | None = None,
) -> str:
    api_base = (ep.api_base or "").rstrip("/")
    if not api_base:
        raise RuntimeError("Endpoint missing api_base")
    url = f"{api_base}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if ep.api_key:
        headers["Authorization"] = f"Bearer {ep.api_key}"

    payload = {
        "model": model or ep.model or settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": settings.LLM_TEMPERATURE,
    }
    resp = curl_requests.post(
        url, json=payload, headers=headers,
        impersonate=_IMPERSONATE, timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ─── Helpers ─────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```\w*\n?|\n?```$")


def _parse_json(text: str) -> dict:
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    return json.loads(cleaned)


def _truncate_sample(sample: _RumorSampleIn) -> _RumorSampleIn:
    text = sample.raw_text
    max_chars = settings.LLM_MAX_INPUT_CHARS
    if len(text) > max_chars:
        logger.warning("Input truncated from %d to %d chars", len(text), max_chars)
        return sample.model_copy(update={"raw_text": text[:max_chars]})
    return sample


def _truncate_exc(exc: Exception | None, limit: int = 300) -> str:
    if exc is None:
        return "(none)"
    msg = str(exc)
    lower = msg.lower()
    if "<html" in lower or "<head" in lower:
        m = re.search(r"<title>(.*?)</title>", msg, re.IGNORECASE | re.DOTALL)
        hint = m.group(1).strip() if m else "HTML error page"
        return f"{type(exc).__name__}: server returned HTML ({hint})"
    if len(msg) > limit:
        return f"{type(exc).__name__}: {msg[:limit]}…"
    return f"{type(exc).__name__}: {msg}"
