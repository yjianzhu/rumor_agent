import logging
import re
from hashlib import sha1
from pathlib import Path
from typing import Protocol

from src.config import settings
from src.db.models import RumorStatus
from src.db.schemas import RumorCreate, _RumorSampleIn, StructuredRumorAnalysis
from src.llm.client import AdkLlmClient

logger = logging.getLogger(__name__)


class StructuredAnalyzer(Protocol):
    def analyze(self, sample: _RumorSampleIn) -> StructuredRumorAnalysis: ...


VERDICT_SIGNALS: dict[RumorStatus, tuple[str, ...]] = {
    RumorStatus.FAKE: (
        "谣言", "假消息", "不实", "辟谣", "系谣言", "虚假",
        "false", "fake", "hoax", "debunked", "misleading",
    ),
    RumorStatus.TRUE: (
        "属实", "真实", "证实", "确认", "是真的",
        "confirmed", "verified", "true",
    ),
    RumorStatus.OUTDATED: (
        "过时", "已过时", "旧闻", "旧消息",
        "outdated", "old rumor",
    ),
}


def analyze_sample(
    sample: _RumorSampleIn,
    *,
    model: str | None = None,
    client: StructuredAnalyzer | None = None,
) -> StructuredRumorAnalysis:
    if client is not None:
        result = client.analyze(sample)
        return normalize_structured_analysis(sample, result)

    endpoints = settings.llm_endpoint_list
    last_exc: Exception | None = None
    for i, ep in enumerate(endpoints):
        try:
            c = AdkLlmClient(
                model=model or ep.model,
                api_key=ep.api_key,
                api_base=ep.api_base,
            )
            result = c.analyze(sample)
            return normalize_structured_analysis(sample, result)
        except Exception as exc:
            last_exc = exc
            logger.warning("LLM endpoint %d (%s) failed: %s", i, ep.api_base, exc)
    raise last_exc  # type: ignore[misc]


def analyze_markdown(
    path: Path,
    *,
    title: str | None = None,
    tags: list[str] | None = None,
    source_urls: list[str] | None = None,
    is_published: bool = False,
    model: str | None = None,
    client: StructuredAnalyzer | None = None,
) -> StructuredRumorAnalysis:
    """Read a Markdown file and analyze its content via LLM."""
    raw_text = path.read_text(encoding="utf-8").strip()
    sample = _RumorSampleIn(
        raw_text=raw_text,
        title=title or path.stem,
        tags=tags,
        source_urls=source_urls,
        is_published=is_published,
    )
    return analyze_sample(sample, model=model, client=client)


def build_preview_analysis(sample: _RumorSampleIn) -> StructuredRumorAnalysis:
    return normalize_structured_analysis(
        sample,
        StructuredRumorAnalysis(
            title=sample.title or derive_title(sample.raw_text),
            summary=None,
            rumor_content=sample.raw_text,
            truth_content=None,
            status=RumorStatus.DUBIOUS,
            tags=sample.tags,
            source_urls=sample.source_urls,
            analysis_summary=None,
            truthfulness_score=0.0,
            evidence=None,
        ),
    )


def to_rumor_create(
    data: StructuredRumorAnalysis,
    *,
    slug: str,
    is_published: bool,
    media_files: list | None = None,
) -> RumorCreate:
    return RumorCreate(
        title=data.title,
        slug=slug,
        summary=data.summary,
        rumor_content=data.rumor_content,
        truth_content=data.truth_content,
        status=data.status,
        tags=data.tags,
        media_files=media_files,
        source_urls=data.source_urls,
        is_published=is_published,
    )


def normalize_structured_analysis(
    sample: _RumorSampleIn,
    analysis: StructuredRumorAnalysis,
) -> StructuredRumorAnalysis:
    status = analysis.status
    if status is not RumorStatus.DUBIOUS and not has_explicit_verdict_signal(sample.raw_text, status):
        status = RumorStatus.DUBIOUS

    return StructuredRumorAnalysis(
        title=clean_text(analysis.title) or clean_text(sample.title) or derive_title(sample.raw_text),
        summary=clean_text(analysis.summary),
        rumor_content=sample.raw_text.strip(),
        truth_content=clean_text(analysis.truth_content),
        status=status,
        tags=dedupe_strings([*(sample.tags or []), *(analysis.tags or [])]) or None,
        source_urls=merge_source_urls(sample.source_urls, analysis.source_urls),
        analysis_summary=clean_text(analysis.analysis_summary),
        truthfulness_score=analysis.truthfulness_score,
        evidence=clean_text(analysis.evidence),
    )


def derive_title(raw_text: str, max_length: int = 48) -> str:
    collapsed = " ".join(raw_text.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3].rstrip() + "..."


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def merge_source_urls(primary: list[str] | None, secondary: list[str] | None) -> list[str] | None:
    merged = dedupe_strings([*(primary or []), *(secondary or [])])
    return merged or None


def has_explicit_verdict_signal(text: str, status: RumorStatus) -> bool:
    if status is RumorStatus.DUBIOUS:
        return True
    lowered = text.casefold()
    return any(_contains_signal(lowered, signal.casefold()) for signal in VERDICT_SIGNALS[status])


def _contains_signal(text: str, signal: str) -> bool:
    if signal.isascii():
        pattern = r"\b" + re.escape(signal) + r"\b"
        return re.search(pattern, text) is not None
    return signal in text


def slugify(text: str) -> str:
    normalized = re.sub(r"\s+", "-", text.strip().lower())
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]", "", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-_")
    return normalized or "rumor"


def hash_suffix(raw_text: str) -> str:
    return sha1(raw_text.encode("utf-8")).hexdigest()[:8]
