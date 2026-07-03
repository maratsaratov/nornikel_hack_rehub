import os
from uuid import uuid4

from werkzeug.utils import secure_filename

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


EXTRACTORS = {
    "pdf": PDFExtractor,
    "docx": DOCXExtractor,
    "xlsx": XLSXExtractor,
    "csv": CSVExtractor,
    "txt": TXTExtractor,
}


class IngestionError(RuntimeError):
    pass


def ensure_upload_dir() -> str:
    upload_dir = os.path.abspath(Config.UPLOAD_DIR)
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def save_upload(project_id: int, file_storage) -> SourceDocument:
    if not file_storage or not file_storage.filename:
        raise IngestionError("No file was provided")

    upload_dir = ensure_upload_dir()
    original_filename = os.path.basename(file_storage.filename)
    file_type = detect_file_type(original_filename)
    safe_name = secure_filename(original_filename)
    if not safe_name:
        extension = os.path.splitext(original_filename)[1].lower()
        safe_name = f"upload{extension}"
    stored_name = f"{uuid4().hex}_{safe_name}"
    stored_path = os.path.abspath(os.path.join(upload_dir, f"project_{project_id}", stored_name))
    os.makedirs(os.path.dirname(stored_path), exist_ok=True)
    file_storage.save(stored_path)

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
    return document


def parse_document(document_id: int):
    document = db.session.get(SourceDocument, document_id)
    if not document:
        raise IngestionError("Document not found")

    run = DocumentParseRun(document_id=document.id, status="running", warnings_json=[])
    db.session.add(run)
    db.session.flush()

    try:
        result = _parse_document_file(document)
        _replace_document_content(document, result)
        document.parse_status = "parsed"
        run.status = "parsed"
        run.warnings_json = result.warnings
        run.error = None
    except UnsupportedFormatError as exc:
        document.parse_status = "unsupported"
        run.status = "unsupported"
        run.warnings_json = ["format unsupported"]
        run.error = str(exc)
    except Exception as exc:
        document.parse_status = "failed"
        run.status = "failed"
        run.warnings_json = []
        run.error = str(exc)

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

    result = extractor_cls().extract(document.stored_path, document.filename)
    result.chunks = build_chunks(result.sections, result.tables)
    return result


def _replace_document_content(document: SourceDocument, result):
    DocumentChunk.query.filter_by(document_id=document.id).delete()
    DocumentTable.query.filter_by(document_id=document.id).delete()

    document.file_type = result.file_type
    document.raw_text = result.raw_text
    document.metadata_json = result.metadata

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
    db.session.delete(document)
    db.session.commit()

    try:
        inside_upload_dir = os.path.commonpath([upload_dir, stored_path]) == upload_dir
    except ValueError:
        inside_upload_dir = False

    if inside_upload_dir and os.path.exists(stored_path):
        os.remove(stored_path)

