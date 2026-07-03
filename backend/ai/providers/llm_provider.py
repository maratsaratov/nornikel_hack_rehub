from abc import abstractmethod

from ai.providers.base import BaseProvider


class LLMProvider(BaseProvider):
    name = "llm"

    @abstractmethod
    def complete(self, messages, **kwargs):
        raise NotImplementedError

