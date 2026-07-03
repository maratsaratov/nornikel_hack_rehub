import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional


SUPPORTED_FILE_TYPES = {"pdf", "docx", "xlsx", "csv", "txt"}

EXTENSION_TO_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".txt": "txt",
    ".doc": "doc",
}

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def detect_file_type(filename: str) -> str:
    _, ext = os.path.splitext(filename or "")
    return EXTENSION_TO_TYPE.get(ext.lower(), (ext.lower().lstrip(".") or "unknown"))


def is_supported_file_type(file_type: str) -> bool:
    return file_type in SUPPORTED_FILE_TYPES


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


def clean_text(text: Optional[str]) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def normalize_cell_value(value: Any) -> Any:
    value = json_safe(value)
    if isinstance(value, str):
        value = value.strip()
        return value if value != "" else None
    return value


def normalize_authors(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r";|,|\band\b", str(value)) if part.strip()]


def extract_year(*values: Any) -> Optional[int]:
    for value in values:
        if not value:
            continue
        if isinstance(value, (datetime, date)):
            return value.year
        match = YEAR_RE.search(str(value))
        if match:
            return int(match.group(0))
    return None


def detect_language(text: str) -> Optional[str]:
    sample = (text or "")[:20000]
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    total = cyrillic + latin
    if total < 40:
        return None
    if cyrillic / total > 0.55:
        return "ru"
    if latin / total > 0.55:
        return "en"
    return "mixed"


def extract_references(text: str) -> List[str]:
    seen = set()
    refs = []
    for match in list(DOI_RE.findall(text or "")) + list(URL_RE.findall(text or "")):
        key = match.strip().rstrip(".,;")
        if key and key.lower() not in seen:
            refs.append(key)
            seen.add(key.lower())
    return refs[:25]


def first_meaningful_line(text: str) -> Optional[str]:
    for line in (text or "").splitlines():
        line = line.strip()
        if 4 <= len(line) <= 180:
            return line
    return None


def build_base_metadata(
    filename: str,
    file_type: str,
    document_properties: Optional[Dict[str, Any]] = None,
    sheet_names: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    return {
        "filename": filename,
        "original_file_type": file_type,
        "title": None,
        "authors": [],
        "year": None,
        "source_type": None,
        "language": None,
        "keywords": [],
        "organization": None,
        "references": [],
        "sheet_names": list(sheet_names or []),
        "document_properties": json_safe(document_properties or {}),
    }


def enrich_metadata(
    metadata: Dict[str, Any],
    text: str = "",
    title: Optional[str] = None,
    authors: Any = None,
    source_type: Optional[str] = None,
    organization: Optional[str] = None,
    keywords: Any = None,
    year_values: Iterable[Any] = (),
) -> Dict[str, Any]:
    metadata = dict(metadata or {})
    props = metadata.get("document_properties") or {}
    metadata["title"] = title or metadata.get("title") or props.get("title") or first_meaningful_line(text)
    metadata["authors"] = normalize_authors(authors or metadata.get("authors") or props.get("author"))
    metadata["year"] = metadata.get("year") or extract_year(*year_values, props.get("created"), props.get("modified"), text)
    metadata["source_type"] = source_type or metadata.get("source_type")
    metadata["language"] = metadata.get("language") or detect_language(text)
    metadata["keywords"] = normalize_authors(keywords or metadata.get("keywords") or props.get("keywords"))
    metadata["organization"] = organization or metadata.get("organization") or props.get("organization")
    metadata["references"] = metadata.get("references") or extract_references(text)
    metadata["document_properties"] = json_safe(props)
    return metadata


def classify_table(name: Optional[str], headers: Iterable[str]) -> Optional[str]:
    haystack = " ".join([name or "", *[str(header or "") for header in headers]]).lower()
    rules = [
        ("parameters", ("parameter", "setting", "input", "factor", "condition")),
        ("experiments", ("experiment", "trial", "run", "sample id", "batch")),
        ("results", ("result", "output", "yield", "score", "metric", "performance")),
        ("compositions", ("composition", "alloy", "component", "element", "formula", "material")),
        ("reference", ("reference", "lookup", "standard", "baseline", "catalog")),
    ]
    for label, keywords in rules:
        if any(keyword in haystack for keyword in keywords):
            return label
    return None

