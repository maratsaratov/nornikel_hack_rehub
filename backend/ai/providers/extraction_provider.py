from abc import abstractmethod

from ai.providers.base import BaseProvider


class ExtractionProvider(BaseProvider):
    name = "extraction"

    @abstractmethod
    def extract(self, payload, **kwargs):
        raise NotImplementedError

