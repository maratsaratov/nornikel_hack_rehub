"""Извлечение содержания изображений (.png/.jpg) через vision-модель.

Изображение отправляется в мультимодальную модель (Config.IMAGE_MODEL, напр.
qwen/qwen3.7-plus через routerai), которая возвращает текстовое описание: текст с
картинки, числа, подписи, смысл графиков/таблиц/схем. Результат сохраняется как
обычный текстовый источник в библиотеке — с явной пометкой, что это изображение.
"""
import base64
import os

import llm
from config import Config
from ingestion.extractors.base import BaseExtractor, ExtractorError
from ingestion.metadata import build_base_metadata, clean_text, enrich_metadata, first_meaningful_line
from ingestion.schemas import ParsedSection, ParseResult

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_IMAGE_MARKER = "[Источник — изображение; текст извлечён vision-моделью]"


class ImageExtractor(BaseExtractor):
    file_type = "image"

    def extract(self, path: str, filename: str) -> ParseResult:
        ext = os.path.splitext(filename)[1].lower()
        mime = _MIME.get(ext, "image/png")
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            raise ExtractorError(f"Не удалось прочитать изображение: {exc}")
        if not raw:
            raise ExtractorError("Пустой файл изображения")

        data_uri = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
        try:
            description, _usage = llm.describe_image(data_uri)
        except Exception as exc:  # noqa - любая ошибка vision-модели → понятное сообщение
            raise ExtractorError(f"Vision-модель не смогла обработать изображение: {exc}")

        description = clean_text(description)
        warnings = []
        if not description:
            description = "Модель не смогла извлечь содержательное описание изображения."
            warnings.append("Vision model returned empty description")

        raw_text = f"{_IMAGE_MARKER}\n\n{description}"
        sections = [ParsedSection(title="Описание изображения", text=raw_text, order=1)]

        metadata = build_base_metadata(
            filename,
            self.file_type,
            document_properties={"is_image": True, "vision_model": Config.IMAGE_MODEL},
        )
        metadata = enrich_metadata(
            metadata,
            text=description,
            title=first_meaningful_line(description) or f"Изображение: {filename}",
        )
        metadata["is_image"] = True
        metadata["source_type"] = "image"

        return ParseResult(
            filename=filename,
            file_type=self.file_type,
            raw_text=raw_text,
            sections=sections,
            metadata=metadata,
            warnings=warnings,
        )
