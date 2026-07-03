from abc import ABC


class ProviderUnavailableError(RuntimeError):
    pass


class BaseProvider(ABC):
    name = "base"

    def health(self) -> dict:
        return {"ok": True, "provider": self.name}

