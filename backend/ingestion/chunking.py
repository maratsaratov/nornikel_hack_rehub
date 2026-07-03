import json
import re
from typing import Iterable, List

from ingestion.schemas import ParsedChunk, ParsedSection, ParsedTable


DEFAULT_MAX_CHARS = 1600
DEFAULT_OVERLAP_CHARS = 180


def _paragraphs(text: str) -> List[str]:
    blocks = re.split(r"\n\s*\n", text or "")
    if len(blocks) == 1:
        blocks = re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я0-9])", text or "")
    return [re.sub(r"\s+", " ", block).strip() for block in blocks if block.strip()]


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("; ", start, end), text.rfind(" ", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap_chars) if overlap_chars else end
    return chunks


def _page_ref(section: ParsedSection) -> str:
    if section.page_from and section.page_to and section.page_from != section.page_to:
        return f"{section.page_from}-{section.page_to}"
    if section.page_from:
        return str(section.page_from)
    return None


def chunk_sections(
    sections: Iterable[ParsedSection],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> List[ParsedChunk]:
    chunks = []
    for section in sections:
        current = []
        current_len = 0
        for paragraph in _paragraphs(section.text):
            if len(paragraph) > max_chars:
                if current:
                    chunks.append(_section_chunk(section, " ".join(current)))
                    current = []
                    current_len = 0
                for piece in _split_long_text(paragraph, max_chars, overlap_chars):
                    chunks.append(_section_chunk(section, piece))
                continue
            if current and current_len + len(paragraph) + 1 > max_chars:
                chunks.append(_section_chunk(section, " ".join(current)))
                current = []
                current_len = 0
            current.append(paragraph)
            current_len += len(paragraph) + 1
        if current:
            chunks.append(_section_chunk(section, " ".join(current)))
    return chunks


def _section_chunk(section: ParsedSection, text: str) -> ParsedChunk:
    return ParsedChunk(
        text=text,
        section_title=section.title,
        page=_page_ref(section),
        meta={
            "kind": "text",
            "section_order": section.order,
            "page_from": section.page_from,
            "page_to": section.page_to,
            **(section.meta or {}),
        },
    )


def chunk_tables(tables: Iterable[ParsedTable]) -> List[ParsedChunk]:
    chunks = []
    for table in tables:
        sample_rows = table.rows[:3]
        sample = json.dumps(sample_rows, ensure_ascii=False, default=str)
        columns = ", ".join(table.columns)
        text = (
            f"Table {table.name or table.sheet_name or 'data'}"
            f" has {len(table.rows)} rows and columns: {columns}."
        )
        if sample_rows:
            text = f"{text} Sample rows: {sample}"
        chunks.append(ParsedChunk(
            text=text,
            section_title=table.name or table.sheet_name,
            page=table.sheet_name,
            meta={
                "kind": "table_summary",
                "table_name": table.name,
                "sheet_name": table.sheet_name,
                "data_range": table.data_range,
                "classification": table.classification,
                "columns": table.columns,
                "row_count": len(table.rows),
                **(table.meta or {}),
            },
        ))
    return chunks


def build_chunks(
    sections: Iterable[ParsedSection],
    tables: Iterable[ParsedTable],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> List[ParsedChunk]:
    return [
        *chunk_sections(sections, max_chars=max_chars, overlap_chars=overlap_chars),
        *chunk_tables(tables),
    ]

