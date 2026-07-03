from ai.config import load_ai_config
from ai.providers.noop_provider import (
    NoopEmbeddingProvider,
    NoopExtractionProvider,
    NoopLLMProvider,
)


def get_llm_provider():
    config = load_ai_config()
    if config.llm_provider != "noop":
        raise ValueError(f"AI LLM provider is not implemented: {config.llm_provider}")
    return NoopLLMProvider()


def get_embedding_provider():
    config = load_ai_config()
    if config.embedding_provider != "noop":
        raise ValueError(f"AI embedding provider is not implemented: {config.embedding_provider}")
    return NoopEmbeddingProvider()


def get_extraction_provider():
    config = load_ai_config()
    if config.extraction_provider != "noop":
        raise ValueError(f"AI extraction provider is not implemented: {config.extraction_provider}")
    return NoopExtractionProvider()

