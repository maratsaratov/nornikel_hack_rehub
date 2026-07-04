from __future__ import annotations

from openai import OpenAI

from config import Config


class ParserAIAgentError(RuntimeError):
    pass


class ParserAIAgent:
    name = "parser-ai-agent"

    def __init__(self):
        if not Config.AI_PARSER_AGENT_ENABLED:
            raise ParserAIAgentError("Parser AI agent is disabled")
        if Config.AI_PARSER_AGENT_PROVIDER != "openrouter":
            raise ParserAIAgentError(
                f"Unsupported parser AI agent provider: {Config.AI_PARSER_AGENT_PROVIDER}"
            )
        if not Config.OPENAI_API_KEY:
            raise ParserAIAgentError("OPENAI_API_KEY is required for the parser AI agent")
        self._client = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_API_BASE,
            timeout=30.0,
        )

    @property
    def model(self) -> str:
        return Config.AI_PARSER_AGENT_MODEL

    def describe(self) -> dict:
        return {
            "name": self.name,
            "provider": Config.AI_PARSER_AGENT_PROVIDER,
            "model": self.model,
            "enabled": Config.AI_PARSER_AGENT_ENABLED,
        }

    def review_text(self, text: str, *, file_name: str | None = None, instructions: str | None = None) -> dict:
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            raise ParserAIAgentError("No text was provided for parser AI review")

        prompt = self._build_prompt(
            cleaned_text[: Config.AI_PARSER_AGENT_MAX_INPUT_CHARS],
            file_name=file_name,
            instructions=instructions,
        )

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": Config.AI_PARSER_AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=Config.AI_PARSER_AGENT_MAX_TOKENS,
            temperature=Config.AI_PARSER_AGENT_TEMPERATURE,
            extra_headers={
                "HTTP-Referer": "https://hypothesis-factory.local",
                "X-Title": "Hypothesis Factory Parser AI Agent",
            },
        )

        return {
            "text": (response.choices[0].message.content or "").strip(),
            "agent": self.describe(),
            "usage": _usage(response),
        }

    def _build_prompt(self, text: str, *, file_name: str | None = None, instructions: str | None = None) -> str:
        parts = [
            "Review and improve the parsed document text.",
            "Preserve facts, numbers, units, formulas, terminology, and overall structure.",
            "Fix obvious OCR, encoding, and parser artifacts only where the correction is well supported by the text.",
            "If a fragment is doubtful, keep it conservative and mark it as [неуверенно].",
            "Return only the improved text.",
        ]
        if file_name:
            parts.append(f"Filename: {file_name}")
        if instructions:
            parts.append(f"Extra instructions: {instructions.strip()}")
        parts.append("")
        parts.append(text)
        return "\n".join(parts)


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
