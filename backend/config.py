"""Конфигурация приложения из переменных окружения."""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # ── Database ────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql://hypo:hypo_secret@localhost:5432/hypofactory"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # ── LLM (OpenRouter / DeepSeek) ─────────────────────────────────────────
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek/deepseek-v4-flash")
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "7000"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.6"))

    # OpenAlex
    OPENALEX_API_URL = os.getenv("OPENALEX_API_URL", "https://api.openalex.org")
    OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "")
    OPENALEX_TIMEOUT = float(os.getenv("OPENALEX_TIMEOUT", "12"))
    OPENALEX_PER_PAGE = int(os.getenv("OPENALEX_PER_PAGE", "6"))

    # Document ingestion
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "storage", "uploads"))
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))

    # Future AI provider layer. The current hypothesis engine still uses llm.py.
    AI_DEFAULT_PROVIDER = os.getenv("AI_DEFAULT_PROVIDER", "noop")
    AI_LLM_PROVIDER = os.getenv("AI_LLM_PROVIDER", AI_DEFAULT_PROVIDER)
    AI_EMBEDDING_PROVIDER = os.getenv("AI_EMBEDDING_PROVIDER", AI_DEFAULT_PROVIDER)
    AI_EXTRACTION_PROVIDER = os.getenv("AI_EXTRACTION_PROVIDER", AI_DEFAULT_PROVIDER)

    # ── App behaviour ───────────────────────────────────────────────────────
    SEED_DEMO = _bool("SEED_DEMO", True)
