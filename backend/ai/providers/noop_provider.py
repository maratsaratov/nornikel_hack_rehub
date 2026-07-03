from ai.providers.base import ProviderUnavailableError
from ai.providers.embedding_provider import EmbeddingProvider
from ai.providers.extraction_provider import ExtractionProvider
from ai.providers.llm_provider import LLMProvider


class NoopLLMProvider(LLMProvider):
    name = "noop-llm"

    def complete(self, messages, **kwargs):
        raise ProviderUnavailableError("No LLM provider is configured")


class NoopEmbeddingProvider(EmbeddingProvider):
    name = "noop-embedding"

    def embed(self, texts, **kwargs):
        raise ProviderUnavailableError("No embedding provider is configured")


class NoopExtractionProvider(ExtractionProvider):
    name = "noop-extraction"

    def extract(self, payload, **kwargs):
        raise ProviderUnavailableError("No extraction provider is configured")

