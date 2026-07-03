from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParsedSection:
    title: Optional[str]
    text: str
    order: int
    page_from: Optional[int] = None
    page_to: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedTable:
    name: Optional[str]
    sheet_name: Optional[str]
    columns: List[str]
    rows: List[Dict[str, Any]]
    data_range: Optional[str] = None
    classification: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["row_count"] = len(self.rows)
        return data


@dataclass
class ParsedChunk:
    text: str
    section_title: Optional[str]
    page: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParseResult:
    filename: str
    file_type: str
    raw_text: str = ""
    sections: List[ParsedSection] = field(default_factory=list)
    tables: List[ParsedTable] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunks: List[ParsedChunk] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "raw_text": self.raw_text,
            "sections": [section.to_dict() for section in self.sections],
            "tables": [table.to_dict() for table in self.tables],
            "metadata": self.metadata,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "warnings": self.warnings,
        }

