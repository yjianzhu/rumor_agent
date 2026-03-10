import json
import logging
from uuid import uuid4

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.db.schemas import _RumorSampleIn, StructuredRumorAnalysis

logger = logging.getLogger(__name__)


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
"""


class AdkLlmClient:
    def __init__(self, model: str | None = None, temperature: float | None = None):
        self.model = model or settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE if temperature is None else temperature

        from google.adk.agents import LlmAgent
        from google.adk.models.lite_llm import LiteLlm
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        model_kwargs: dict[str, object] = {}
        if settings.LLM_API_KEY:
            model_kwargs["api_key"] = settings.LLM_API_KEY
        if settings.LLM_API_BASE:
            model_kwargs["api_base"] = settings.LLM_API_BASE


        self._types = types
        self._output_key = "structured_result"
        self._app_name = "rumor-agent"
        self._user_id = "rumor-agent-cli"
        self._session_service = InMemorySessionService()
        self._agent = LlmAgent(
            name="rumor_structurer",
            model=LiteLlm(model=self.model, **model_kwargs),
            instruction=PROMPT,
            input_schema=_RumorSampleIn,
            output_schema=StructuredRumorAnalysis,
            output_key=self._output_key,
            generate_content_config=types.GenerateContentConfig(temperature=self.temperature),
        )
        self._runner = Runner(
            app_name=self._app_name,
            agent=self._agent,
            session_service=self._session_service,
        )

    @retry(
        stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def analyze(self, sample: _RumorSampleIn) -> StructuredRumorAnalysis:
        sample = self._truncate_input(sample)
        session = self._session_service.create_session_sync(
            app_name=self._app_name,
            user_id=self._user_id,
            session_id=str(uuid4()),
        )
        message = self._types.UserContent(
            parts=[self._types.Part(text=sample.model_dump_json())]
        )
        final_text = None

        for event in self._runner.run(
            user_id=self._user_id,
            session_id=session.id,
            new_message=message,
        ):
            parts = getattr(getattr(event, "content", None), "parts", None) or []
            text_parts = [part.text for part in parts if getattr(part, "text", None)]
            if text_parts:
                final_text = "\n".join(text_parts).strip()

        stored_session = self._session_service.get_session_sync(
            app_name=self._app_name,
            user_id=self._user_id,
            session_id=session.id,
        )
        payload = stored_session.state.get(self._output_key) if stored_session else None
        return StructuredRumorAnalysis.model_validate(self._coerce_payload(payload or final_text))

    @staticmethod
    def _coerce_payload(payload: object) -> dict:
        if payload is None:
            raise RuntimeError("LLM returned no structured payload")
        if hasattr(payload, "model_dump"):
            return payload.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            return json.loads(payload)
        raise TypeError(f"Unsupported payload type: {type(payload)!r}")

    def _truncate_input(self, sample: _RumorSampleIn) -> _RumorSampleIn:
        text = sample.raw_text
        max_chars = settings.LLM_MAX_INPUT_CHARS
        try:
            import litellm
            token_count = litellm.token_counter(model=self.model, text=text)
            model_max = litellm.get_max_tokens(self.model) or 128_000
            limit = int(model_max * 0.7)
            if token_count > limit:
                ratio = limit / token_count
                truncated = text[: int(len(text) * ratio)]
                logger.warning(
                    "Input truncated from %d to ~%d tokens (model limit %d)",
                    token_count, limit, model_max,
                )
                return sample.model_copy(update={"raw_text": truncated})
        except Exception:
            pass
        if len(text) > max_chars:
            logger.warning("Input truncated from %d to %d chars (fallback)", len(text), max_chars)
            return sample.model_copy(update={"raw_text": text[:max_chars]})
        return sample
