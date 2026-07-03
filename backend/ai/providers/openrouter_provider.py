import json
import re

from openai import OpenAI

from ai.config import load_ai_config
from ai.providers.base import ProviderUnavailableError
from ai.providers.extraction_provider import ExtractionProvider


class OpenRouterExtractionProvider(ExtractionProvider):
    name = "openrouter-extraction"

    def __init__(self):
        self.config = load_ai_config()
        if not self.config.api_key:
            raise ProviderUnavailableError("AI_API_KEY or OPENAI_API_KEY is required for OpenRouter extraction")
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.api_base,
            timeout=30.0,
        )

    def extract(self, payload, **kwargs):
        system = payload.get("system")
        user = payload.get("user")
        if not system or not user:
            raise ValueError("Extraction payload must include system and user prompts")

        response = self._client.chat.completions.create(
            model=kwargs.get("model") or self.config.parser_review_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_tokens=kwargs.get("max_tokens") or self.config.parser_review_max_tokens,
            temperature=kwargs.get("temperature", self.config.parser_review_temperature),
            extra_headers={
                "HTTP-Referer": "https://hypothesis-factory.local",
                "X-Title": "Hypothesis Factory Parser Review",
            },
        )
        content = response.choices[0].message.content or "{}"
        return {
            "data": _extract_json(content),
            "model": kwargs.get("model") or self.config.parser_review_model,
            "usage": _usage(response),
        }


def _usage(response):
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _extract_json(text: str):
    text = (text or "").strip()
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise
