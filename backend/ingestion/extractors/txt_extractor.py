import re

from ingestion.extractors.base import BaseExtractor, ExtractorError
from ingestion.metadata import build_base_metadata, clean_text, enrich_metadata, first_meaningful_line
from ingestion.schemas import ParsedSection, ParseResult


class TXTExtractor(BaseExtractor):
    file_type = "txt"

    def extract(self, path: str, filename: str) -> ParseResult:
        text, encoding = self._read_text(path)
        raw_text = clean_text(text)
        sections = self._sections(raw_text)
        warnings = []
        if not raw_text:
            warnings.append("TXT contains no extractable text")

        metadata = build_base_metadata(
            filename,
            self.file_type,
            document_properties={"encoding": encoding},
        )
        metadata = enrich_metadata(
            metadata,
            text=raw_text,
            title=first_meaningful_line(raw_text),
        )

        return ParseResult(
            filename=filename,
            file_type=self.file_type,
            raw_text=raw_text,
            sections=sections,
            metadata=metadata,
            warnings=warnings,
        )

    def _read_text(self, path):
        encodings = ("utf-8-sig", "utf-8", "cp1251", "latin-1")
        last_error = None
        for encoding in encodings:
            try:
                with open(path, "r", encoding=encoding) as handle:
                    return handle.read(), encoding
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ExtractorError(f"Failed to decode TXT: {last_error}")

    def _sections(self, text: str):
        sections = []
        current_title = "Text"
        buffer = []
        order = 1

        def flush():
            nonlocal order, buffer
            body = clean_text("\n".join(buffer))
            if body:
                sections.append(ParsedSection(title=current_title, text=body, order=order))
                order += 1
            buffer = []

        for line in (text or "").splitlines():
            stripped = line.strip()
            if self._looks_like_heading(stripped):
                flush()
                current_title = stripped.lstrip("#").strip()
            elif stripped:
                buffer.append(stripped)
            else:
                buffer.append("")
        flush()
        return sections

    def _looks_like_heading(self, line: str) -> bool:
        if not line or len(line) > 120:
            return False
        if line.startswith("#"):
            return True
        if re.match(r"^\d+(\.\d+)*\s+\S+", line):
            return True
        if line.endswith("."):
            return False
        words = line.split()
        return 1 <= len(words) <= 10 and sum(word[:1].isupper() for word in words) >= max(1, len(words) // 2)

