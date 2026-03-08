import re
from hashlib import sha1
from typing import Protocol

from src.db.models import RumorStatus
from src.db.schemas import RumorCreate, RumorSampleIn, StructuredRumorAnalysis
from src.llm.client import AdkLlmClient


class StructuredAnalyzer(Protocol):
    def analyze(self, sample: RumorSampleIn) -> StructuredRumorAnalysis: ...


VERDICT_SIGNALS: dict[RumorStatus, tuple[str, ...]] = {
    RumorStatus.FAKE: (
        "\u8c23\u8a00",
        "\u5047\u6d88\u606f",
        "\u4e0d\u5b9e",
        "\u8f9f\u8c23",
        "\u7cfb\u8c23\u8a00",
        "\u865a\u5047",
        "false",
        "fake",
        "hoax",
        "debunked",
        "misleading",
    ),
    RumorStatus.TRUE: (
        "\u5c5e\u5b9e",
        "\u771f\u5b9e",
        "\u8bc1\u5b9e",
        "\u786e\u8ba4",
        "\u662f\u771f\u7684",
        "confirmed",
        "verified",
        "true",
    ),
    RumorStatus.OUTDATED: (
        "\u8fc7\u65f6",
        "\u5df2\u8fc7\u65f6",
        "\u65e7\u95fb",
        "\u65e7\u6d88\u606f",
        "outdated",
        "old rumor",
    ),
}


def analyze_sample(
    sample: RumorSampleIn,
    *,
    model: str | None = None,
    client: StructuredAnalyzer | None = None,
) -> StructuredRumorAnalysis:
    analyzer = client or AdkLlmClient(model=model)
    result = analyzer.analyze(sample)
    return normalize_structured_analysis(sample, result)


def build_preview_analysis(sample: RumorSampleIn) -> StructuredRumorAnalysis:
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


def to_rumor_create(data: StructuredRumorAnalysis, *, slug: str, is_published: bool) -> RumorCreate:
    return RumorCreate(
        title=data.title,
        slug=slug,
        summary=data.summary,
        rumor_content=data.rumor_content,
        truth_content=data.truth_content,
        status=data.status,
        tags=data.tags,
        source_urls=data.source_urls,
        is_published=is_published,
    )


def normalize_structured_analysis(
    sample: RumorSampleIn,
    analysis: StructuredRumorAnalysis,
) -> StructuredRumorAnalysis:
    status = analysis.status
    if status is not RumorStatus.DUBIOUS and not has_explicit_verdict_signal(sample.raw_text, status):
        status = RumorStatus.DUBIOUS

    return StructuredRumorAnalysis(
        title=clean_text(sample.title) or clean_text(analysis.title) or derive_title(sample.raw_text),
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
