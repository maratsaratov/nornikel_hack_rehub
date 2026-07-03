"""Конфигурация приложения из переменных окружения."""
import os
from dotenv import load_dotenv

load_dotenv()


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

    # ── App behaviour ───────────────────────────────────────────────────────
    SEED_DEMO = _bool("SEED_DEMO", True)
