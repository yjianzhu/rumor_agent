from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DB_USER: str = "postgres"
    DB_PASSWORD: str = "password"
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "rumor_agent"

    LLM_API_KEY: str | None = None
    LLM_API_BASE: str | None = None
    LLM_MODEL: str = "openai/gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_RETRIES: int = 3
    LLM_MAX_INPUT_CHARS: int = 30000
    MEDIA_DIR: str = "media"
    IMPORT_BATCH_SIZE: int = 50
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    DEDUP_SIMILARITY_THRESHOLD: float = 0.92

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Config()
