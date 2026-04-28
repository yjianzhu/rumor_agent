import logging

from curl_cffi import requests as curl_requests

from src.config import ApiEndpoint, settings

logger = logging.getLogger(__name__)

_IMPERSONATE = "chrome136"
_TIMEOUT = 60


def get_embedding(text: str) -> list[float]:
    endpoints = settings.embedding_endpoint_list
    last_exc: Exception | None = None
    for i, ep in enumerate(endpoints):
        try:
            return _call_embedding(text, ep)
        except Exception as exc:
            last_exc = exc
            logger.warning("Embedding endpoint %d (%s) failed: %s", i, ep.api_base, exc)
    raise last_exc  # type: ignore[misc]


def _call_embedding(text: str, ep: ApiEndpoint) -> list[float]:
    model = ep.model or settings.EMBEDDING_MODEL
    url = f"{ep.api_base.rstrip('/')}/embeddings"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if ep.api_key:
        headers["Authorization"] = f"Bearer {ep.api_key}"

    payload = {"model": model, "input": [text]}
    resp = curl_requests.post(
        url, json=payload, headers=headers,
        impersonate=_IMPERSONATE, timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["data"][0]["embedding"]
