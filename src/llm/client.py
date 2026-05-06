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

STRUCTURED_PROMPT = """You convert rumor samples into structured database-ready records.

Rules:
- Your job is limited to structuring the input text and producing text-internal analysis.
- Do not claim you performed web search, retrieval, external verification, or fact checking.
- If the sample does not contain an explicit verdict signal, set status to DUBIOUS.
- truthfulness_score means confidence in the extracted verdict from the input text, not real-world truth probability.
- evidence must only cite or summarize statements visible in the input sample.
- title should be short and specific.
- rumor_content must stay faithful to the input raw_text.
- source_urls may only include URLs provided in the input or explicitly present in the raw_text.
- Return a complete structured result that matches the schema exactly.
- Return ONLY a JSON object, no markdown fences or extra text.
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
