from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class ApiEndpoint:
    api_key: str | None = None
    api_base: str | None = None
    model: str | None = None


@dataclass
class Config:
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "password"
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "rumor_agent"

    LLM_MODEL: str = "openai/gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_RETRIES: int = 3
    LLM_MAX_INPUT_CHARS: int = 30000
    LLM_ENDPOINTS: list[ApiEndpoint] = field(default_factory=list)

    EMBEDDING_MODEL: str = "openai/Qwen/Qwen3-Embedding-4B"
    EMBEDDING_DIM: int = 2560
    DEDUP_SIMILARITY_THRESHOLD: float = 0.92
    EMBEDDING_ENDPOINTS: list[ApiEndpoint] = field(default_factory=list)

    XHS_MCP_URL: str = "http://127.0.0.1:18060/mcp"
    XHS_MAX_ITEMS: int = 20
    XHS_DELAY_RANGE: tuple[float, float] = (1.5, 4.0)
    XHS_RETRY_DELAY_RANGE: tuple[float, float] = (3.0, 6.0)
    XHS_MAX_RETRIES: int = 3

    COLLECT_KEYWORDS: list[str] = field(default_factory=list)
    BILI_MIN_PLAY: int = 100
    BILI_COMMENT_TOP_N: int = 10
    XHS_COMMENT_TOP_N: int = 10
    BILI_COMMENT_CONCURRENCY: int = 3

    MEDIA_DIR: str = "media"
    IMPORT_BATCH_SIZE: int = 50

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def LLM_API_KEY(self) -> str | None:
        return self.LLM_ENDPOINTS[0].api_key if self.LLM_ENDPOINTS else None

    @property
    def LLM_API_BASE(self) -> str | None:
        return self.LLM_ENDPOINTS[0].api_base if self.LLM_ENDPOINTS else None

    @property
    def llm_endpoint_list(self) -> list[ApiEndpoint]:
        return list(self.LLM_ENDPOINTS)

    @property
    def embedding_endpoint_list(self) -> list[ApiEndpoint]:
        return list(self.EMBEDDING_ENDPOINTS)


def _load_config(path: Path = _CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    db = data.get("database", {})
    llm = data.get("llm", {})
    emb = data.get("embedding", {})
    gen = data.get("general", {})
    xhs = data.get("xhs", {})
    collect = data.get("collect", {})

    delay = xhs.get("delay_range", [1.5, 4.0])
    retry_delay = xhs.get("retry_delay_range", [3.0, 6.0])

    return Config(
        DB_USER=db.get("user", "postgres"),
        DB_PASSWORD=db.get("password", "password"),
        DB_HOST=db.get("host", "localhost"),
        DB_PORT=str(db.get("port", 5432)),
        DB_NAME=db.get("name", "rumor_agent"),
        LLM_MODEL=llm.get("model", "openai/gpt-4o-mini"),
        LLM_TEMPERATURE=float(llm.get("temperature", 0.0)),
        LLM_MAX_RETRIES=int(llm.get("max_retries", 3)),
        LLM_MAX_INPUT_CHARS=int(llm.get("max_input_chars", 30000)),
        LLM_ENDPOINTS=[ApiEndpoint(**ep) for ep in llm.get("endpoints", [])],
        EMBEDDING_MODEL=emb.get("model", "openai/Qwen/Qwen3-Embedding-4B"),
        EMBEDDING_DIM=int(emb.get("dim", 2560)),
        DEDUP_SIMILARITY_THRESHOLD=float(emb.get("dedup_similarity_threshold", 0.92)),
        EMBEDDING_ENDPOINTS=[ApiEndpoint(**ep) for ep in emb.get("endpoints", [])],
        XHS_MCP_URL=xhs.get("mcp_url", "http://127.0.0.1:18060/mcp"),
        XHS_MAX_ITEMS=int(xhs.get("max_items", 20)),
        XHS_DELAY_RANGE=(float(delay[0]), float(delay[1])),
        XHS_RETRY_DELAY_RANGE=(float(retry_delay[0]), float(retry_delay[1])),
        XHS_MAX_RETRIES=int(xhs.get("max_retries", 3)),
        COLLECT_KEYWORDS=collect.get("keywords", []),
        BILI_MIN_PLAY=int(collect.get("bili_min_play", 100)),
        BILI_COMMENT_TOP_N=int(collect.get("bili_comment_top_n", 10)),
        XHS_COMMENT_TOP_N=int(collect.get("xhs_comment_top_n", 10)),
        BILI_COMMENT_CONCURRENCY=int(collect.get("bili_comment_concurrency", 3)),
        MEDIA_DIR=gen.get("media_dir", "media"),
        IMPORT_BATCH_SIZE=int(gen.get("import_batch_size", 50)),
    )


settings = _load_config()
