from __future__ import annotations

import logging
from time import perf_counter

from openai import OpenAI

from config import Config

logger = logging.getLogger(__name__)


class ParserAIAgentError(RuntimeError):
    pass


class ParserAIAgent:
    name = "parser-ai-agent"
    _SUPPORTED_PROVIDERS = {"openrouter", "routerai"}

    def __init__(self):
        if not Config.AI_PARSER_AGENT_ENABLED:
            logger.info("Parser AI agent initialization skipped: agent disabled")
            raise ParserAIAgentError("Parser AI agent is disabled")
        provider = (Config.AI_PARSER_AGENT_PROVIDER or "").strip().lower()
        if provider not in self._SUPPORTED_PROVIDERS:
            logger.warning(
                "Parser AI agent initialization failed: unsupported provider provider=%s supported=%s",
                Config.AI_PARSER_AGENT_PROVIDER,
                sorted(self._SUPPORTED_PROVIDERS),
            )
            raise ParserAIAgentError(
                f"Unsupported parser AI agent provider: {Config.AI_PARSER_AGENT_PROVIDER}"
            )
        if not Config.OPENAI_API_KEY:
            logger.warning(
                "Parser AI agent initialization failed: OPENAI_API_KEY missing provider=%s base_url=%s model=%s",
                provider,
                Config.OPENAI_API_BASE,
                Config.AI_PARSER_AGENT_MODEL,
            )
            raise ParserAIAgentError("OPENAI_API_KEY is required for the parser AI agent")
        self._client = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_API_BASE,
            timeout=30.0,
        )
        logger.info(
            "Parser AI agent initialized provider=%s model=%s base_url=%s max_input_chars=%s max_tokens=%s temperature=%s",
            provider,
            Config.AI_PARSER_AGENT_MODEL,
            Config.OPENAI_API_BASE,
            Config.AI_PARSER_AGENT_MAX_INPUT_CHARS,
            Config.AI_PARSER_AGENT_MAX_TOKENS,
            Config.AI_PARSER_AGENT_TEMPERATURE,
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
            logger.warning("Parser AI review skipped: empty text file_name=%s", file_name)
            raise ParserAIAgentError("No text was provided for parser AI review")

        truncated_text = cleaned_text[: Config.AI_PARSER_AGENT_MAX_INPUT_CHARS]
        prompt = self._build_prompt(
            truncated_text,
            file_name=file_name,
            instructions=instructions,
        )

        request_started_at = perf_counter()
        logger.info(
            "Parser AI review request started file_name=%s input_chars=%s truncated=%s prompt_chars=%s instructions=%s provider=%s model=%s",
            file_name,
            len(cleaned_text),
            len(cleaned_text) > len(truncated_text),
            len(prompt),
            bool((instructions or "").strip()),
            Config.AI_PARSER_AGENT_PROVIDER,
            self.model,
        )
        try:
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
        except Exception:
            logger.exception(
                "Parser AI review request failed file_name=%s provider=%s model=%s after %.2fs",
                file_name,
                Config.AI_PARSER_AGENT_PROVIDER,
                self.model,
                perf_counter() - request_started_at,
            )
            raise

        output_text = (response.choices[0].message.content or "").strip()
        usage = _usage(response)
        logger.info(
            "Parser AI review request completed file_name=%s output_chars=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s in %.2fs",
            file_name,
            len(output_text),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
            perf_counter() - request_started_at,
        )

        return {
            "text": output_text,
            "agent": self.describe(),
            "usage": usage,
        }

    def summarize_text(
        self,
        text: str,
        *,
        file_name: str | None = None,
        file_type: str | None = None,
        title: str | None = None,
    ) -> dict:
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            logger.warning(
                "Parser AI summary skipped: empty text file_name=%s file_type=%s",
                file_name,
                file_type,
            )
            raise ParserAIAgentError("No text was provided for parser AI summary")

        truncated_text = cleaned_text[: Config.AI_PARSER_AGENT_MAX_INPUT_CHARS]
        prompt = self._build_summary_prompt(
            truncated_text,
            file_name=file_name,
            file_type=file_type,
            title=title,
        )

        request_started_at = perf_counter()
        logger.info(
            "Parser AI summary request started file_name=%s file_type=%s title_present=%s input_chars=%s truncated=%s prompt_chars=%s provider=%s model=%s",
            file_name,
            file_type,
            bool((title or "").strip()),
            len(cleaned_text),
            len(cleaned_text) > len(truncated_text),
            len(prompt),
            Config.AI_PARSER_AGENT_PROVIDER,
            self.model,
        )
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._summary_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=min(Config.AI_PARSER_AGENT_MAX_TOKENS, 220),
                temperature=min(Config.AI_PARSER_AGENT_TEMPERATURE, 0.2),
                extra_headers={
                    "HTTP-Referer": "https://hypothesis-factory.local",
                    "X-Title": "Hypothesis Factory Parser Summary",
                },
            )
        except Exception:
            logger.exception(
                "Parser AI summary request failed file_name=%s file_type=%s provider=%s model=%s after %.2fs",
                file_name,
                file_type,
                Config.AI_PARSER_AGENT_PROVIDER,
                self.model,
                perf_counter() - request_started_at,
            )
            raise

        summary = _normalize_inline_text(response.choices[0].message.content or "")
        usage = _usage(response)
        logger.info(
            "Parser AI summary request completed file_name=%s file_type=%s output_chars=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s in %.2fs",
            file_name,
            file_type,
            len(summary),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
            perf_counter() - request_started_at,
        )

        return {
            "summary": summary,
            "agent": self.describe(),
            "usage": usage,
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

    def _build_summary_prompt(
        self,
        text: str,
        *,
        file_name: str | None = None,
        file_type: str | None = None,
        title: str | None = None,
    ) -> str:
        parts = [
            "Ниже дано содержимое распарсенного научного или технического документа.",
            "Сделай краткую сводку по смыслу основного текста документа.",
            "Пиши по-русски.",
            "Верни только 1-2 предложения без маркеров и без пояснений о себе.",
            "Опирайся прежде всего на внутреннее содержание документа, а не на имя файла или заголовок.",
            "Не пересказывай только название документа.",
            "Не выдумывай факты, авторов, результаты или выводы, которых нет в тексте.",
            "Если текст шумный или неполный, дай осторожную общую сводку о теме документа.",
            "",
            "Текст документа:",
            text,
        ]
        context = []
        if file_name:
            context.append(f"Имя файла: {file_name}")
        if file_type:
            context.append(f"Тип файла: {file_type}")
        if title:
            context.append(f"Заголовок: {title.strip()}")
        if context:
            parts.append("")
            parts.append("Контекст файла: используй только если он не противоречит содержимому.")
            parts.extend(context)
        return "\n".join(parts)

    def _summary_system_prompt(self) -> str:
        return (
            "You create short Russian summaries for parsed scientific and technical documents. "
            "Use only the provided text, stay factual, concise, and avoid hallucinations. "
            "Return plain text only."
        )


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _normalize_inline_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip(" -:;,.\"'")
