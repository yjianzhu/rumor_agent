import json
from uuid import uuid4

from src.config import settings
from src.db.schemas import RumorSampleIn, StructuredRumorAnalysis


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

        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for LLM analysis")

        from google.adk.agents import LlmAgent
        from google.adk.models.lite_llm import LiteLlm
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        model_kwargs: dict[str, object] = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_API_BASE:
            model_kwargs["api_base"] = settings.OPENAI_API_BASE

        self._types = types
        self._output_key = "structured_result"
        self._app_name = "rumor-agent"
        self._user_id = "rumor-agent-cli"
        self._session_service = InMemorySessionService()
        self._agent = LlmAgent(
            name="rumor_structurer",
            model=LiteLlm(model=self.model, **model_kwargs),
            instruction=PROMPT,
            input_schema=RumorSampleIn,
            output_schema=StructuredRumorAnalysis,
            output_key=self._output_key,
            generate_content_config=types.GenerateContentConfig(temperature=self.temperature),
        )
        self._runner = Runner(
            app_name=self._app_name,
            agent=self._agent,
            session_service=self._session_service,
        )

    def analyze(self, sample: RumorSampleIn) -> StructuredRumorAnalysis:
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
