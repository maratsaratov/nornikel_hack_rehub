import logging
import os
import re
import shutil
from time import perf_counter
from uuid import uuid4

from fastapi import UploadFile

from config import Config
from db import db
from ingestion.chunking import build_chunks
from ingestion.extractors.base import ExtractorError, UnsupportedFormatError
from ingestion.extractors.csv_extractor import CSVExtractor
from ingestion.extractors.docx_extractor import DOCXExtractor
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
}

SUMMARY_MAX_CHARS = 220
SUMMARY_MIN_ALPHA_CHARS = 12
SUMMARY_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


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


def _build_document_summary(result) -> str | None:
    metadata = dict(result.metadata or {})
    title = str(metadata.get("title") or "").strip().lower()
    candidates = []

    for block in re.split(r"\n{2,}", result.raw_text or ""):
        for sentence in SUMMARY_SENTENCE_SPLIT_RE.split(block):
            fragment = _normalize_summary_fragment(sentence)
            if not fragment:
                continue
            lowered = fragment.lower()
            if title and lowered == title:
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
        return _trim_summary(" ".join(unique_fragments))

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
    if fragment:
        return _trim_summary(fragment)

    return None


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
    summary = _build_document_summary(result)
    if summary:
        metadata["summary"] = summary
        metadata["description"] = summary
    else:
        metadata.pop("summary", None)
        metadata.pop("description", None)
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
        sorted((result.metadata or {}).keys()),
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

