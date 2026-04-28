import json
import logging

from curl_cffi import requests as curl_requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.db.schemas import _RumorSampleIn, StructuredRumorAnalysis

logger = logging.getLogger(__name__)

_IMPERSONATE = "chrome136"
_TIMEOUT = 120

PROMPT = """You convert rumor samples into structured database-ready records.

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


class CurlLlmClient:
    """OpenAI-compatible chat completion client backed by curl_cffi."""

    def __init__(
        self,
        model: str | None = None,
        temperature: float | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        self.model = model or settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE if temperature is None else temperature
        self.api_key = api_key or settings.LLM_API_KEY
        self.api_base = (api_base or settings.LLM_API_BASE or "").rstrip("/")

    @retry(
        stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def analyze(self, sample: _RumorSampleIn) -> StructuredRumorAnalysis:
        sample = self._truncate_input(sample)
        schema_hint = json.dumps(
            StructuredRumorAnalysis.model_json_schema(), ensure_ascii=False,
        )
        user_content = (
            f"JSON Schema for your response:\n{schema_hint}\n\n"
            f"Sample:\n{sample.model_dump_json()}"
        )
        raw = self._chat(PROMPT, user_content)
        return StructuredRumorAnalysis.model_validate(self._parse_json(raw))

    def _chat(self, system: str, user: str) -> str:
        url = f"{self.api_base}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        resp = curl_requests.post(
            url, json=payload, headers=headers,
            impersonate=_IMPERSONATE, timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _parse_json(text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.index("\n")
            cleaned = cleaned[first_nl + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        return json.loads(cleaned)

    def _truncate_input(self, sample: _RumorSampleIn) -> _RumorSampleIn:
        text = sample.raw_text
        max_chars = settings.LLM_MAX_INPUT_CHARS
        if len(text) > max_chars:
            logger.warning("Input truncated from %d to %d chars", len(text), max_chars)
            return sample.model_copy(update={"raw_text": text[:max_chars]})
        return sample


# Backward-compatible alias
AdkLlmClient = CurlLlmClient
