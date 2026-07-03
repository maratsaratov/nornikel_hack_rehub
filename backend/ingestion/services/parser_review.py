import json

from ai.factory import get_extraction_provider
from config import Config
from db import db
from models import DocumentChunk, DocumentParseRun, DocumentTable, SourceDocument


PARSER_REVIEW_SYSTEM_PROMPT = """You are a deterministic document parser QA reviewer.

Your task is to review the parser output, not to re-parse the original document.
Use only the provided JSON payload. Do not invent missing facts, authors, years,
metadata, tables, or citations. If a field is absent, mark it as absent.

Check:
- whether extracted text appears non-empty and coherent for the file type;
- whether chunking preserves section/page/sheet context;
- whether metadata is separated from text and not hallucinated;
- whether table extraction looks structured for CSV/XLSX/DOCX tables;
- whether warnings/status are consistent with the extracted content;
- whether the parser likely needs OCR, unsupported-format handling, or manual review.

Return only valid JSON with this schema:
{
  "status": "ok|warning|failed",
  "confidence": 0.0,
  "summary": "short parser QA summary",
  "issues": [
    {
      "severity": "low|medium|high",
      "code": "short_code",
      "message": "concrete issue",
      "evidence": "exact evidence from provided payload"
    }
  ],
  "suggested_actions": ["concrete action"],
  "metadata_gaps": ["missing metadata field"],
  "needs_ocr": false,
  "needs_manual_review": false
}
"""


class ParserReviewPreconditionError(ValueError):
    pass


def build_parser_review_user_prompt(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    max_chars = Config.AI_PARSER_REVIEW_INPUT_CHARS
    if len(encoded) > max_chars:
        encoded = encoded[:max_chars].rstrip() + "\n...TRUNCATED_FOR_REVIEW"
    return (
        "Review this parsed document payload. Remember: evaluate parser quality only, "
        "do not generate hypotheses and do not enrich the document.\n\n"
        f"{encoded}"
    )


def review_document_parse(document_id: int) -> dict:
    document = db.session.get(SourceDocument, document_id)
    if not document:
        raise ValueError("Document not found")
    if document.parse_status == "uploaded":
        raise ParserReviewPreconditionError("Document must be parsed before review")

    payload = build_parser_review_payload(document)
    provider = get_extraction_provider()
    result = provider.extract(
        {
            "system": PARSER_REVIEW_SYSTEM_PROMPT,
            "user": build_parser_review_user_prompt(payload),
        },
        model=Config.AI_PARSER_REVIEW_MODEL,
        max_tokens=Config.AI_PARSER_REVIEW_MAX_TOKENS,
        temperature=Config.AI_PARSER_REVIEW_TEMPERATURE,
    )
    review = _normalize_review(result.get("data") or {})
    return {
        "document_id": document.id,
        "provider": getattr(provider, "name", "unknown"),
        "model": result.get("model", Config.AI_PARSER_REVIEW_MODEL),
        "review": review,
        "usage": result.get("usage", {}),
    }


def build_parser_review_payload(document: SourceDocument) -> dict:
    chunks = document.chunks.order_by(DocumentChunk.chunk_index.asc()).limit(10).all()
    tables = document.tables.order_by(DocumentTable.id.asc()).limit(5).all()
    recent_run = document.parse_runs.order_by(DocumentParseRun.created_at.desc()).first()
    raw_text = " ".join((document.raw_text or "").split())

    return {
        "document": {
            "id": document.id,
            "filename": document.filename,
            "file_type": document.file_type,
            "parse_status": document.parse_status,
            "metadata": document.metadata_json or {},
            "raw_text_length": len(document.raw_text or ""),
            "raw_text_preview": _preview(raw_text, 1800),
            "chunk_count": document.chunks.count(),
            "table_count": document.tables.count(),
        },
        "recent_parse_run": recent_run.to_dict() if recent_run else None,
        "chunks_sample": [
            {
                "index": chunk.chunk_index,
                "section_title": chunk.section_title,
                "page_ref": chunk.page_ref,
                "text": _preview(chunk.text, 700),
                "meta": chunk.meta_json or {},
            }
            for chunk in chunks
        ],
        "tables_sample": [
            _table_review_sample(table.to_dict())
            for table in tables
        ],
    }


def _table_review_sample(table: dict) -> dict:
    table_json = table.get("table_json") or {}
    rows = table_json.get("rows") or []
    return {
        "table_name": table.get("table_name"),
        "sheet_name": table.get("sheet_name"),
        "columns": table_json.get("columns") or [],
        "row_count": table_json.get("row_count", len(rows)),
        "data_range": table_json.get("data_range"),
        "classification": table_json.get("classification"),
        "rows_sample": rows[:3],
    }


def _normalize_review(data: dict) -> dict:
    status = data.get("status")
    if status not in {"ok", "warning", "failed"}:
        status = "warning"
    return {
        "status": status,
        "confidence": _bounded_float(data.get("confidence"), default=0.0),
        "summary": str(data.get("summary") or "").strip(),
        "issues": data.get("issues") if isinstance(data.get("issues"), list) else [],
        "suggested_actions": data.get("suggested_actions") if isinstance(data.get("suggested_actions"), list) else [],
        "metadata_gaps": data.get("metadata_gaps") if isinstance(data.get("metadata_gaps"), list) else [],
        "needs_ocr": bool(data.get("needs_ocr")),
        "needs_manual_review": bool(data.get("needs_manual_review")),
    }


def _bounded_float(value, default=0.0):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _preview(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."
