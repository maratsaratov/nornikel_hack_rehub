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

    # ── Reranker (OpenRouter -> Cohere rerank) ──────────────────────────────
    # Второй этап RAG: переупорядочивает кандидатов кросс-энкодером.
    RERANK_MODEL = os.getenv("RERANK_MODEL", "cohere/rerank-4-fast")
    RERANK_ENABLED = _bool("RERANK_ENABLED", True)
    RERANK_TIMEOUT = float(os.getenv("RERANK_TIMEOUT", "30"))
    RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "24"))  # размер пула 1-го этапа

    # ── RAG (chunking + BM25 1-й этап) ───────────────────────────────────────
    RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "900"))       # символов на пассаж
    RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
    BM25_K1 = float(os.getenv("BM25_K1", "1.5"))                   # насыщение частоты терма
    BM25_B = float(os.getenv("BM25_B", "0.75"))                    # нормировка по длине
    # Мультиязычность: минимум кандидатов на каждый язык (RU/EN) в пуле реранкера,
    # чтобы англо- и русскоязычные источники честно сравнил мультиязычный реранкер.
    RETRIEVAL_MIN_PER_LANG = int(os.getenv("RETRIEVAL_MIN_PER_LANG", "5"))

    # ── Dense-ретривер (bge-m3 через OpenRouter) + гибридное слияние ──────────
    EMBED_MODEL = os.getenv("EMBED_MODEL", "baai/bge-m3")
    EMBED_ENABLED = _bool("EMBED_ENABLED", True)
    EMBED_TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "30"))
    EMBED_BATCH = int(os.getenv("EMBED_BATCH", "96"))
    # Reciprocal Rank Fusion: BM25 (лексика) + dense (семантика)
    HYBRID_RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
    HYBRID_BM25_WEIGHT = float(os.getenv("HYBRID_BM25_WEIGHT", "1.0"))
    HYBRID_DENSE_WEIGHT = float(os.getenv("HYBRID_DENSE_WEIGHT", "1.0"))

    # ── Внешние научные источники (умный парсер базы знаний) ─────────────────
    # Активные коннекторы по умолчанию (keyless). Materials Project включается
    # автоматически, если задан MP_API_KEY.
    EXTERNAL_SOURCES = os.getenv("EXTERNAL_SOURCES", "openalex,crossref,semantic_scholar")
    EXTERNAL_TIMEOUT = float(os.getenv("EXTERNAL_TIMEOUT", "15"))
    CROSSREF_API_URL = os.getenv("CROSSREF_API_URL", "https://api.crossref.org")
    SEMANTIC_SCHOLAR_API_URL = os.getenv("SEMANTIC_SCHOLAR_API_URL", "https://api.semanticscholar.org")
    SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    MP_API_URL = os.getenv("MP_API_URL", "https://api.materialsproject.org")
    MP_API_KEY = os.getenv("MP_API_KEY", "")   # Materials Project (опционально)
    CONTACT_MAILTO = os.getenv("CONTACT_MAILTO", os.getenv("OPENALEX_MAILTO", "hypofactory@example.com"))

    # OpenAlex
    OPENALEX_API_URL = os.getenv("OPENALEX_API_URL", "https://api.openalex.org")
    OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "")
    OPENALEX_TIMEOUT = float(os.getenv("OPENALEX_TIMEOUT", "12"))
    OPENALEX_PER_PAGE = int(os.getenv("OPENALEX_PER_PAGE", "6"))

    # ── App behaviour ───────────────────────────────────────────────────────
    SEED_DEMO = _bool("SEED_DEMO", True)
