from dataclasses import dataclass

from config import Config


@dataclass(frozen=True)
class AIProviderConfig:
    default_provider: str = "noop"
    llm_provider: str = "noop"
    embedding_provider: str = "noop"
    extraction_provider: str = "noop"


def load_ai_config() -> AIProviderConfig:
    return AIProviderConfig(
        default_provider=Config.AI_DEFAULT_PROVIDER,
        llm_provider=Config.AI_LLM_PROVIDER,
        embedding_provider=Config.AI_EMBEDDING_PROVIDER,
        extraction_provider=Config.AI_EXTRACTION_PROVIDER,
    )

