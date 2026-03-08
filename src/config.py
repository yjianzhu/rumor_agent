import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "rumor_agent")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
    LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
    
    @property
    def DATABASE_URL(self):
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Config()
