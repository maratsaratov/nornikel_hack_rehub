from ingestion.extractors.base import BaseExtractor, ExtractorError, missing_dependency
from ingestion.metadata import build_base_metadata, clean_text, enrich_metadata, json_safe
from ingestion.schemas import ParsedSection, ParseResult


class PDFExtractor(BaseExtractor):
    file_type = "pdf"

    def extract(self, path: str, filename: str) -> ParseResult:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise missing_dependency("pypdf", self.file_type) from exc

        warnings = []
        try:
            reader = PdfReader(path)
        except Exception as exc:
            raise ExtractorError(f"Failed to read PDF: {exc}") from exc

        document_properties = {}
        metadata_obj = getattr(reader, "metadata", None)
        if metadata_obj:
            try:
                document_properties = {
                    str(key).lstrip("/").lower(): json_safe(value)
                    for key, value in dict(metadata_obj).items()
                }
            except Exception:
                document_properties = {}

        sections = []
        pages_text = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = clean_text(page.extract_text() or "")
            except Exception as exc:
                warnings.append(f"Failed to extract text from page {index}: {exc}")
                text = ""
            if text:
                pages_text.append(text)
                sections.append(ParsedSection(
                    title=f"Page {index}",
                    text=text,
                    order=index,
                    page_from=index,
                    page_to=index,
                ))

        raw_text = "\n\n".join(pages_text)
        if not raw_text:
            warnings.append("No extractable text found. Scanned PDF/OCR is not supported in MVP.")

        metadata = build_base_metadata(filename, self.file_type, document_properties=document_properties)
        metadata = enrich_metadata(
            metadata,
            text=raw_text,
            title=document_properties.get("title"),
            authors=document_properties.get("author"),
            year_values=(document_properties.get("creationdate"), document_properties.get("moddate")),
        )
        stream = getattr(reader, "stream", None)
        if stream:
            try:
                stream.close()
            except Exception:
                pass

        return ParseResult(
            filename=filename,
            file_type=self.file_type,
            raw_text=raw_text,
            sections=sections,
            metadata=metadata,
            warnings=warnings,
        )

