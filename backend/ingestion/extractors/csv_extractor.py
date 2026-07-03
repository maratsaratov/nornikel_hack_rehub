import csv
from io import StringIO

from ingestion.extractors.base import BaseExtractor, ExtractorError
from ingestion.metadata import (
    build_base_metadata,
    classify_table,
    enrich_metadata,
    normalize_cell_value,
)
from ingestion.schemas import ParsedSection, ParsedTable, ParseResult


MAX_TABLE_ROWS = 10000


class CSVExtractor(BaseExtractor):
    file_type = "csv"

    def extract(self, path: str, filename: str) -> ParseResult:
        warnings = []
        text, encoding = self._read_text(path)
        try:
            dialect, has_header = self._dialect(text)
            rows = list(csv.reader(StringIO(text), dialect))
        except Exception as exc:
            raise ExtractorError(f"Failed to read CSV: {exc}") from exc

        rows = self._trim_rows(rows)
        if not rows:
            warnings.append("CSV contains no rows")

        headers, data_rows = self._split_header(rows, has_header)
        if len(data_rows) > MAX_TABLE_ROWS:
            warnings.append(f"CSV was truncated to {MAX_TABLE_ROWS} rows")
            data_rows = data_rows[:MAX_TABLE_ROWS]

        table = ParsedTable(
            name=filename,
            sheet_name=None,
            columns=headers,
            rows=[self._row_dict(headers, row) for row in data_rows],
            data_range=f"R1C1:R{len(rows)}C{len(headers)}" if rows else None,
            classification=classify_table(filename, headers),
            meta={"encoding": encoding, "has_header": has_header},
        )
        raw_text = f"CSV '{filename}' contains {len(data_rows)} data rows and {len(headers)} columns."
        sections = [ParsedSection(title=filename, text=raw_text, order=1, meta={"encoding": encoding})]
        metadata = build_base_metadata(
            filename,
            self.file_type,
            document_properties={"encoding": encoding, "has_header": has_header},
        )
        metadata = enrich_metadata(metadata, text=raw_text, source_type="dataset")

        return ParseResult(
            filename=filename,
            file_type=self.file_type,
            raw_text=raw_text,
            sections=sections,
            tables=[table] if rows else [],
            metadata=metadata,
            warnings=warnings,
        )

    def _read_text(self, path):
        encodings = ("utf-8-sig", "utf-8", "cp1251", "latin-1")
        last_error = None
        for encoding in encodings:
            try:
                with open(path, "r", encoding=encoding, newline="") as handle:
                    return handle.read(), encoding
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ExtractorError(f"Failed to decode CSV: {last_error}")

    def _dialect(self, text):
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        try:
            has_header = csv.Sniffer().has_header(sample)
        except csv.Error:
            has_header = True
        return dialect, has_header

    def _trim_rows(self, rows):
        cleaned = []
        max_width = 0
        for row in rows:
            values = [normalize_cell_value(value) for value in row]
            while values and values[-1] is None:
                values.pop()
            if any(value is not None for value in values):
                cleaned.append(values)
                max_width = max(max_width, len(values))
        return [row + [None] * (max_width - len(row)) for row in cleaned]

    def _split_header(self, rows, has_header):
        if not rows:
            return [], []
        if has_header:
            return self._headers(rows[0]), rows[1:]
        headers = [f"Column {index}" for index in range(1, len(rows[0]) + 1)]
        return headers, rows

    def _headers(self, values):
        headers = []
        seen = {}
        for index, value in enumerate(values, start=1):
            header = str(value or f"Column {index}").strip() or f"Column {index}"
            count = seen.get(header.lower(), 0) + 1
            seen[header.lower()] = count
            headers.append(header if count == 1 else f"{header} {count}")
        return headers

    def _row_dict(self, headers, row):
        return {
            header: normalize_cell_value(row[index]) if index < len(row) else None
            for index, header in enumerate(headers)
        }

