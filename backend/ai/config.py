from dataclasses import dataclass

from config import Config


@dataclass(frozen=True)
class AIProviderConfig:
    default_provider: str = "noop"
    llm_provider: str = "noop"
    embedding_provider: str = "noop"
    extraction_provider: str = "noop"
    api_key: str = ""
    api_base: str = ""
    parser_review_model: str = "qwen/qwen3-4b-instruct-2507"
    parser_review_max_tokens: int = 900
    parser_review_temperature: float = 0.0


def load_ai_config() -> AIProviderConfig:
    return AIProviderConfig(
        default_provider=Config.AI_DEFAULT_PROVIDER,
        llm_provider=Config.AI_LLM_PROVIDER,
        embedding_provider=Config.AI_EMBEDDING_PROVIDER,
        extraction_provider=Config.AI_EXTRACTION_PROVIDER,
        api_key=Config.AI_API_KEY,
        api_base=Config.AI_API_BASE,
        parser_review_model=Config.AI_PARSER_REVIEW_MODEL,
        parser_review_max_tokens=Config.AI_PARSER_REVIEW_MAX_TOKENS,
        parser_review_temperature=Config.AI_PARSER_REVIEW_TEMPERATURE,
    )

