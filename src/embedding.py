import logging

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)
def get_embedding(text: str) -> list[float]:
    resp = litellm.embedding(model=settings.EMBEDDING_MODEL, input=[text])
    return resp.data[0]["embedding"]
