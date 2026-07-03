from abc import abstractmethod

from ai.providers.base import BaseProvider


class EmbeddingProvider(BaseProvider):
    name = "embedding"

    @abstractmethod
    def embed(self, texts, **kwargs):
        raise NotImplementedError

