"""Тонкая обёртка над OpenRouter (совместим с OpenAI SDK).

Модель по умолчанию — deepseek/deepseek-v4-flash: дешёвая reasoning-модель
(~$0.000007 за вызов в наших тестах), что отвечает требованию заказчика
«максимальная экономия ресурсов».
"""
import json
import re
from openai import OpenAI
from config import Config

_client = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_API_BASE,
            timeout=150.0,
        )
    return _client


def _extract_json(text: str):
    """Достаём JSON даже если модель обернула его в ```json ... ``` или текст."""
    if not text:
        raise ValueError("Пустой ответ модели")
    text = text.strip()
    # срезаем markdown-ограждение
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # берём фрагмент от первой { до последней }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _response_format(schema: dict = None, schema_name: str = "response"):
    if schema:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
    return {"type": "json_object"}


def complete_json(system: str, user: str, max_tokens: int = None,
                  temperature: float = None, schema: dict = None,
                  schema_name: str = "response") -> dict:
    """Вызов модели со structured output (json_schema) или JSON-объектом. Возвращает (data, usage)."""
    resp = client().chat.completions.create(
        model=Config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=_response_format(schema, schema_name),
        max_tokens=max_tokens or Config.LLM_MAX_TOKENS,
        temperature=temperature if temperature is not None else Config.LLM_TEMPERATURE,
        extra_headers={
            "HTTP-Referer": "https://hypothesis-factory.local",
            "X-Title": "Hypothesis Factory",
        },
    )
    msg = resp.choices[0].message
    content = msg.content
    # На случай reasoning-модели без content — пробуем reasoning-поле
    if not content and hasattr(msg, "reasoning"):
        content = getattr(msg, "reasoning", None)

    usage = {}
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
        cost = getattr(resp.usage, "cost", None)
        if cost is not None:
            usage["cost_usd"] = cost

    data = _extract_json(content)
    return data, usage


def ping() -> dict:
    """Быстрая проверка доступности модели (для /api/health)."""
    try:
        resp = client().chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        return {"ok": True, "model": Config.OPENAI_MODEL}
    except Exception as e:  # noqa
        return {"ok": False, "model": Config.OPENAI_MODEL, "error": str(e)[:300]}
