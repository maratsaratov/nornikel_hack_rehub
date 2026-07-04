import logging
import os
import re
import shutil
from time import perf_counter
from uuid import uuid4

from fastapi import UploadFile

from ai_parser_agent import ParserAIAgent, ParserAIAgentError
from config import Config
from db import db
from ingestion.chunking import build_chunks
from ingestion.extractors.base import ExtractorError, UnsupportedFormatError
from ingestion.extractors.csv_extractor import CSVExtractor
from ingestion.extractors.docx_extractor import DOCXExtractor
from ingestion.extractors.image_extractor import ImageExtractor
from ingestion.extractors.pdf_extractor import PDFExtractor
from ingestion.extractors.txt_extractor import TXTExtractor
from ingestion.extractors.xlsx_extractor import XLSXExtractor
from ingestion.metadata import build_base_metadata, detect_file_type, is_supported_file_type
from models import DocumentChunk, DocumentParseRun, DocumentTable, SourceDocument

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


EXTRACTORS = {
    "pdf": PDFExtractor,
    "docx": DOCXExtractor,
    "xlsx": XLSXExtractor,
    "csv": CSVExtractor,
    "txt": TXTExtractor,
    "image": ImageExtractor,
}

SUMMARY_MAX_CHARS = 220
SUMMARY_MIN_ALPHA_CHARS = 12
SUMMARY_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
SUMMARY_SAMPLE_BLOCK_CHARS = 900
SUMMARY_TABLE_SAMPLE_ROWS = 3
SUMMARY_TABLE_SAMPLE_COLS = 6


class IngestionError(RuntimeError):
    pass


class FileTooLargeError(IngestionError):
    pass


def _normalize_summary_fragment(text: str) -> str:
    fragment = re.sub(r"\s+", " ", str(text or "")).strip(" -:;,.'\"")
    if len(fragment) < 24:
        return ""
    if sum(1 for char in fragment if char.isalpha()) < SUMMARY_MIN_ALPHA_CHARS:
        return ""
    return fragment


def _trim_summary(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    clipped = normalized[: limit + 1]
    boundary = clipped.rfind(" ")
    if boundary >= int(limit * 0.6):
        clipped = clipped[:boundary]
    else:
        clipped = clipped[:limit]
    return clipped.rstrip(" ,;:-") + "..."


def _summary_key(text: str | None) -> str:
    return "".join(char.lower() for char in str(text or "") if char.isalnum())


def _normalize_block_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _append_summary_block(blocks: list[str], seen: set[str], text: str, *, title: str | None = None) -> None:
    normalized = _normalize_block_text(text)
    if len(normalized) < 40 and sum(1 for char in normalized if char.isalpha()) < SUMMARY_MIN_ALPHA_CHARS:
        return
    if title:
        normalized_title = _normalize_block_text(title)
        if normalized_title and _summary_key(normalized_title) not in _summary_key(normalized[: min(len(normalized), 220)]):
            normalized = f"{normalized_title}\n{normalized}"
            normalized = _normalize_block_text(normalized)
    key = _summary_key(normalized[:320])
    if not key or key in seen:
        return
    seen.add(key)
    blocks.append(normalized)


def _table_sample_columns(table) -> list[str]:
    columns = [str(column).strip() for column in getattr(table, "columns", []) if str(column or "").strip()]
    return columns[:SUMMARY_TABLE_SAMPLE_COLS]


def _table_sample_rows(table, columns: list[str]) -> list[str]:
    sample_rows = []
    fallback_keys = []
    rows = list(getattr(table, "rows", []) or [])
    if len(rows) <= SUMMARY_TABLE_SAMPLE_ROWS:
        selected_indexes = list(range(len(rows)))
    else:
        selected_indexes = [0, len(rows) // 2, len(rows) - 1]

    seen_indexes = set()
    for row_index in selected_indexes:
        if row_index in seen_indexes or row_index < 0 or row_index >= len(rows):
            continue
        seen_indexes.add(row_index)
        row = rows[row_index]
        if not isinstance(row, dict):
            continue
        if not fallback_keys:
            fallback_keys = [str(key).strip() for key in row.keys() if str(key or "").strip()]
        selected_columns = columns or fallback_keys[:SUMMARY_TABLE_SAMPLE_COLS]
        cells = []
        for column in selected_columns[:SUMMARY_TABLE_SAMPLE_COLS]:
            value = _normalize_block_text(row.get(column))
            if not value:
                continue
            cells.append(f"{column}={value}")
        if cells:
            sample_rows.append(f"Row {row_index + 1}: " + "; ".join(cells))
    return sample_rows


def _build_table_summary_block(table) -> str:
    name = _normalize_block_text(getattr(table, "name", "") or getattr(table, "sheet_name", "") or "data")
    details = [f"Table {name}", f"Rows: {len(getattr(table, 'rows', []) or [])}"]
    classification = _normalize_block_text(getattr(table, "classification", ""))
    if classification:
        details.append(f"Type: {classification}")

    columns = _table_sample_columns(table)
    if columns:
        details.append(f"Columns: {', '.join(columns)}")

    sample_rows = _table_sample_rows(table, columns)
    block = ". ".join(details)
    if sample_rows:
        block = f"{block}. Sample rows: " + " | ".join(sample_rows)
    return block


def _summary_title_candidates(document: SourceDocument | None, result) -> list[str]:
    metadata = dict(result.metadata or {})
    candidates = [
        metadata.get("title"),
        metadata.get("subject"),
        metadata.get("filename"),
    ]
    if document:
        candidates.extend([
            document.filename,
            os.path.splitext(document.filename or "")[0],
        ])
    return [str(value).strip() for value in candidates if str(value or "").strip()]


def _looks_like_title_only(summary: str | None, *candidates: str) -> bool:
    summary_key = _summary_key(summary)
    if len(summary_key) < SUMMARY_MIN_ALPHA_CHARS:
        return True
    for candidate in candidates:
        candidate_key = _summary_key(candidate)
        if not candidate_key:
            continue
        if summary_key == candidate_key:
            return True
        if len(summary_key) <= len(candidate_key) + 12 and (
            summary_key.startswith(candidate_key) or candidate_key.startswith(summary_key)
        ):
            return True
    return False


def _build_document_summary(document: SourceDocument | None, result) -> str | None:
    metadata = dict(result.metadata or {})
    title_candidates = _summary_title_candidates(document, result)
    candidates = []

    for block in re.split(r"\n{2,}", result.raw_text or ""):
        for sentence in SUMMARY_SENTENCE_SPLIT_RE.split(block):
            fragment = _normalize_summary_fragment(sentence)
            if not fragment:
                continue
            if _looks_like_title_only(fragment, *title_candidates):
                continue
            candidates.append(fragment)
            if len(candidates) >= 6:
                break
        if len(candidates) >= 6:
            break

    unique_fragments = []
    seen = set()
    for fragment in candidates:
        key = fragment.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_fragments.append(fragment)
        if len(unique_fragments) >= 2:
            break

    if unique_fragments:
        summary = _trim_summary(" ".join(unique_fragments))
        if not _looks_like_title_only(summary, *title_candidates):
            return summary

    sheet_names = [str(name).strip() for name in metadata.get("sheet_names") or [] if str(name).strip()]
    if result.file_type in {"xlsx", "csv"} or metadata.get("source_type") == "dataset":
        details = []
        if sheet_names:
            details.append(f"листы: {', '.join(sheet_names[:3])}")
        if result.tables:
            details.append(f"таблиц: {len(result.tables)}")
        if result.chunks:
            details.append(f"фрагментов: {len(result.chunks)}")
        prefix = "Табличный файл с извлечёнными данными"
        return _trim_summary(f"{prefix}; {', '.join(details)}." if details else prefix)

    first_section = next((section.text for section in result.sections if getattr(section, "text", "").strip()), "")
    fragment = _normalize_summary_fragment(first_section)
    if fragment and not _looks_like_title_only(fragment, *title_candidates):
        return _trim_summary(fragment)

    for table in result.tables:
        table_fragment = _normalize_summary_fragment(_build_table_summary_block(table))
        if table_fragment and not _looks_like_title_only(table_fragment, *title_candidates):
            return _trim_summary(table_fragment)

    return None


def _build_summary_blocks(result) -> list[str]:
    blocks = []
    seen = set()
    for section in result.sections:
        body = str(getattr(section, "text", "") or "").strip()
        if not body:
            continue
        section_title = str(getattr(section, "title", "") or "").strip()
        _append_summary_block(blocks, seen, body, title=section_title)

    for table in getattr(result, "tables", []) or []:
        _append_summary_block(
            blocks,
            seen,
            _build_table_summary_block(table),
            title=getattr(table, "name", None) or getattr(table, "sheet_name", None),
        )

    if blocks:
        return blocks

    for block in re.split(r"\n{2,}", str(result.raw_text or "")):
        _append_summary_block(blocks, seen, block)
    return blocks


def _sample_block_text(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    head_limit = max(int(limit * 0.6), 120)
    tail_limit = max(limit - head_limit - 5, 80)
    head = normalized[:head_limit].rstrip(" ,;:-")
    tail = normalized[-tail_limit:].lstrip(" ,;:-")
    return f"{head} ... {tail}".strip()


def _sample_blocks(blocks: list[str], char_limit: int) -> str:
    if not blocks:
        return ""

    total = len(blocks)
    if total <= 5:
        indexes = list(range(total))
    else:
        indexes = [0, 1, total // 2, max(total - 2, 0), total - 1]

    ordered_indexes = []
    seen = set()
    for index in indexes:
        bounded = max(0, min(total - 1, index))
        if bounded in seen:
            continue
        seen.add(bounded)
        ordered_indexes.append(bounded)

    parts = []
    consumed = 0
    remaining_slots = max(len(ordered_indexes), 1)
    for index in ordered_indexes:
        remaining_budget = char_limit - consumed
        if remaining_budget < 120:
            break
        block_limit = min(
            SUMMARY_SAMPLE_BLOCK_CHARS,
            max(180, remaining_budget // remaining_slots),
        )
        sampled = _sample_block_text(blocks[index], block_limit)
        if not sampled:
            remaining_slots -= 1
            continue
        parts.append(sampled)
        consumed += len(sampled) + 2
        remaining_slots -= 1

    return "\n\n".join(parts).strip()


def _collect_summary_text(result) -> str:
    raw_text = str(result.raw_text or "").strip()
    char_limit = max(Config.AI_PARSER_AGENT_MAX_INPUT_CHARS, SUMMARY_MAX_CHARS)
    sampled_blocks = _sample_blocks(_build_summary_blocks(result), char_limit)
    if sampled_blocks:
        return sampled_blocks

    return raw_text[:char_limit]


def _build_ai_document_summary(document: SourceDocument, result) -> tuple[str | None, dict]:
    if not Config.AI_PARSER_AGENT_ENABLED:
        logger.info(
            "Skipping AI summary document_id=%s filename=%s reason=parser_agent_disabled",
            document.id,
            document.filename,
        )
        return None, {}
    if not Config.OPENAI_API_KEY:
        logger.info(
            "Skipping AI summary document_id=%s filename=%s reason=missing_openai_api_key",
            document.id,
            document.filename,
        )
        return None, {}

    summary_text = _collect_summary_text(result)
    alpha_chars = sum(1 for char in summary_text if char.isalpha())
    logger.info(
        "Prepared AI summary payload document_id=%s filename=%s file_type=%s raw_text_chars=%s sampled_chars=%s alpha_chars=%s sections=%s chunks=%s tables=%s",
        document.id,
        document.filename,
        result.file_type,
        len(result.raw_text or ""),
        len(summary_text),
        alpha_chars,
        len(result.sections),
        len(result.chunks),
        len(result.tables),
    )
    if alpha_chars < SUMMARY_MIN_ALPHA_CHARS:
        logger.info(
            "Skipping AI summary document_id=%s filename=%s reason=insufficient_alpha_chars alpha_chars=%s threshold=%s",
            document.id,
            document.filename,
            alpha_chars,
            SUMMARY_MIN_ALPHA_CHARS,
        )
        return None, {}

    title = str((result.metadata or {}).get("title") or "").strip() or None
    try:
        logger.info(
            "Invoking parser AI summary document_id=%s filename=%s provider=%s model=%s title_present=%s",
            document.id,
            document.filename,
            Config.AI_PARSER_AGENT_PROVIDER,
            Config.AI_PARSER_AGENT_MODEL,
            bool(title),
        )
        agent = ParserAIAgent()
        response = agent.summarize_text(
            summary_text,
            file_name=document.filename,
            file_type=result.file_type,
            title=title,
        )
    except ParserAIAgentError as exc:
        logger.info(
            "Skipping AI summary document_id=%s filename=%s reason=%s",
            document.id,
            document.filename,
            exc,
        )
        return None, {}
    except Exception as exc:
        logger.warning(
            "Failed AI summary document_id=%s filename=%s error=%s",
            document.id,
            document.filename,
            exc,
        )
        return None, {}

    summary = _trim_summary(response.get("summary") or "")
    title_candidates = _summary_title_candidates(document, result)
    if _looks_like_title_only(summary, *title_candidates):
        logger.info(
            "Discarding title-like AI summary document_id=%s filename=%s summary=%s",
            document.id,
            document.filename,
            summary,
        )
        return None, response.get("agent") or {}
    if not summary:
        logger.info(
            "Discarding empty AI summary document_id=%s filename=%s provider=%s model=%s",
            document.id,
            document.filename,
            (response.get("agent") or {}).get("provider"),
            (response.get("agent") or {}).get("model"),
        )
        return None, response.get("agent") or {}

    logger.info(
        "Generated AI summary document_id=%s filename=%s provider=%s model=%s",
        document.id,
        document.filename,
        (response.get("agent") or {}).get("provider"),
        (response.get("agent") or {}).get("model"),
    )
    return summary, response.get("agent") or {}


def _too_large_error() -> str:
    return f"File is too large. Maximum upload size is {Config.MAX_UPLOAD_MB} MB"


def _ensure_upload_size_allowed(size) -> None:
    if size is not None and size > Config.MAX_UPLOAD_BYTES:
        raise FileTooLargeError(_too_large_error())


def ensure_upload_dir() -> str:
    upload_dir = os.path.abspath(Config.UPLOAD_DIR)
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _secure_filename(filename: str) -> str:
    name = os.path.basename(filename or "")
    stem, extension = os.path.splitext(name)
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    safe_extension = re.sub(r"[^A-Za-z0-9.]+", "", extension).lower()
    if safe_extension and not safe_extension.startswith("."):
        safe_extension = f".{safe_extension}"
    return f"{safe_stem or 'upload'}{safe_extension}"


def save_upload(project_id: int, file_storage: UploadFile) -> SourceDocument:
    if not file_storage or not file_storage.filename:
        raise IngestionError("No file was provided")

    started_at = perf_counter()
    upload_dir = ensure_upload_dir()
    original_filename = os.path.basename(file_storage.filename)
    file_type = detect_file_type(original_filename)
    safe_name = _secure_filename(original_filename)
    if not safe_name:
        extension = os.path.splitext(original_filename)[1].lower()
        safe_name = f"upload{extension}"
    stored_name = f"{uuid4().hex}_{safe_name}"
    stored_path = os.path.abspath(os.path.join(upload_dir, f"project_{project_id}", stored_name))
    os.makedirs(os.path.dirname(stored_path), exist_ok=True)
    with open(stored_path, "wb") as dest:
        shutil.copyfileobj(file_storage.file, dest)
    try:
        stored_size = os.path.getsize(stored_path)
        _ensure_upload_size_allowed(stored_size)
    except IngestionError:
        if os.path.exists(stored_path):
            os.remove(stored_path)
        raise

    document = SourceDocument(
        project_id=project_id,
        filename=original_filename,
        stored_path=stored_path,
        file_type=file_type,
        parse_status="uploaded",
        metadata_json=build_base_metadata(original_filename, file_type),
    )
    db.session.add(document)
    db.session.commit()
    logger.info(
        "Saved upload document_id=%s project_id=%s filename=%s file_type=%s size_bytes=%s stored_path=%s in %.2fs",
        document.id,
        project_id,
        original_filename,
        file_type,
        stored_size,
        stored_path,
        perf_counter() - started_at,
    )
    return document


def parse_document(document_id: int):
    document = db.session.get(SourceDocument, document_id)
    if not document:
        raise IngestionError("Document not found")

    started_at = perf_counter()
    run = DocumentParseRun(document_id=document.id, status="running", warnings_json=[])
    db.session.add(run)
    db.session.flush()
    logger.info(
        "Started document parse document_id=%s run_id=%s filename=%s file_type=%s stored_path=%s",
        document.id,
        run.id,
        document.filename,
        document.file_type,
        document.stored_path,
    )

    try:
        result = _parse_document_file(document)
        _replace_document_content(document, result)
        document.parse_status = "parsed"
        run.status = "parsed"
        run.warnings_json = result.warnings
        run.error = None
        logger.info(
            "Completed document parse document_id=%s run_id=%s sections=%s tables=%s chunks=%s warnings=%s in %.2fs",
            document.id,
            run.id,
            len(result.sections),
            len(result.tables),
            len(result.chunks),
            len(result.warnings),
            perf_counter() - started_at,
        )
    except UnsupportedFormatError as exc:
        document.parse_status = "unsupported"
        run.status = "unsupported"
        run.warnings_json = ["format unsupported"]
        run.error = str(exc)
        logger.warning(
            "Unsupported document parse document_id=%s run_id=%s filename=%s file_type=%s error=%s",
            document.id,
            run.id,
            document.filename,
            document.file_type,
            exc,
        )
    except Exception as exc:
        document.parse_status = "failed"
        run.status = "failed"
        run.warnings_json = []
        run.error = str(exc)
        logger.exception(
            "Failed document parse document_id=%s run_id=%s filename=%s file_type=%s after %.2fs",
            document.id,
            run.id,
            document.filename,
            document.file_type,
            perf_counter() - started_at,
        )

    db.session.commit()
    return document, run


def _parse_document_file(document: SourceDocument):
    if not os.path.exists(document.stored_path):
        raise ExtractorError("Stored file is missing")
    if not is_supported_file_type(document.file_type):
        raise UnsupportedFormatError("format unsupported")

    extractor_cls = EXTRACTORS.get(document.file_type)
    if not extractor_cls:
        raise UnsupportedFormatError("format unsupported")

    extraction_started_at = perf_counter()
    logger.info(
        "Extractor selected document_id=%s filename=%s extractor=%s",
        document.id,
        document.filename,
        extractor_cls.__name__,
    )
    result = extractor_cls().extract(document.stored_path, document.filename)
    extraction_elapsed = perf_counter() - extraction_started_at
    logger.info(
        "Extraction finished document_id=%s filename=%s extractor=%s sections=%s tables=%s warnings=%s raw_text_chars=%s in %.2fs",
        document.id,
        document.filename,
        extractor_cls.__name__,
        len(result.sections),
        len(result.tables),
        len(result.warnings),
        len(result.raw_text or ""),
        extraction_elapsed,
    )

    chunking_started_at = perf_counter()
    result.chunks = build_chunks(result.sections, result.tables)
    logger.info(
        "Chunking finished document_id=%s filename=%s chunks=%s in %.2fs",
        document.id,
        document.filename,
        len(result.chunks),
        perf_counter() - chunking_started_at,
    )
    return result


def _replace_document_content(document: SourceDocument, result):
    started_at = perf_counter()
    existing_chunk_count = document.chunks.count() if document.id else 0
    existing_table_count = document.tables.count() if document.id else 0
    logger.info(
        "Persisting parse result document_id=%s existing_chunks=%s existing_tables=%s new_chunks=%s new_tables=%s",
        document.id,
        existing_chunk_count,
        existing_table_count,
        len(result.chunks),
        len(result.tables),
    )
    DocumentChunk.query.filter_by(document_id=document.id).delete()
    DocumentTable.query.filter_by(document_id=document.id).delete()

    document.file_type = result.file_type
    document.raw_text = result.raw_text

    metadata = dict(result.metadata or {})
    heuristic_summary = _build_document_summary(document, result)
    ai_summary, ai_agent = _build_ai_document_summary(document, result)
    summary = ai_summary or heuristic_summary
    if summary:
        metadata["summary"] = summary
        metadata["description"] = summary
        metadata["summary_source"] = "ai" if ai_summary else "heuristic"
        if ai_agent.get("provider"):
            metadata["summary_provider"] = ai_agent["provider"]
        else:
            metadata.pop("summary_provider", None)
        if ai_agent.get("model"):
            metadata["summary_model"] = ai_agent["model"]
        else:
            metadata.pop("summary_model", None)
    else:
        metadata.pop("summary", None)
        metadata.pop("description", None)
        metadata.pop("summary_source", None)
        metadata.pop("summary_provider", None)
        metadata.pop("summary_model", None)
    document.metadata_json = metadata

    for index, chunk in enumerate(result.chunks):
        db.session.add(DocumentChunk(
            document_id=document.id,
            chunk_index=index,
            section_title=chunk.section_title,
            page_ref=str(chunk.page) if chunk.page is not None else None,
            text=chunk.text,
            meta_json=chunk.meta,
        ))

    for table in result.tables:
        db.session.add(DocumentTable(
            document_id=document.id,
            table_name=table.name,
            sheet_name=table.sheet_name,
            table_json=table.to_dict(),
        ))
    logger.info(
        "Persisted parse result document_id=%s chunks=%s tables=%s metadata_keys=%s in %.2fs",
        document.id,
        len(result.chunks),
        len(result.tables),
        sorted(metadata.keys()),
        perf_counter() - started_at,
    )


def document_preview(document: SourceDocument, chunk_limit: int = 5, table_limit: int = 3) -> dict:
    data = document.to_dict(with_raw_text=False)
    data["chunks"] = [
        chunk.to_dict()
        for chunk in document.chunks.order_by(DocumentChunk.chunk_index.asc()).limit(chunk_limit).all()
    ]
    data["tables"] = [
        table.to_dict()
        for table in document.tables.order_by(DocumentTable.id.asc()).limit(table_limit).all()
    ]
    runs = document.parse_runs.order_by(DocumentParseRun.created_at.desc()).limit(3).all()
    data["recent_parse_runs"] = [run.to_dict() for run in runs]
    return data


def delete_document(document: SourceDocument) -> None:
    stored_path = os.path.abspath(document.stored_path)
    upload_dir = ensure_upload_dir()
    logger.info(
        "Deleting document document_id=%s filename=%s stored_path=%s",
        document.id,
        document.filename,
        stored_path,
    )
    db.session.delete(document)
    db.session.commit()

    try:
        inside_upload_dir = os.path.commonpath([upload_dir, stored_path]) == upload_dir
    except ValueError:
        inside_upload_dir = False

    if inside_upload_dir and os.path.exists(stored_path):
        os.remove(stored_path)
        logger.info("Deleted document file document_id=%s stored_path=%s", document.id, stored_path)

