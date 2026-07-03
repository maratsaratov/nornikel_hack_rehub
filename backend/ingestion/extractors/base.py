from abc import ABC, abstractmethod

from ingestion.schemas import ParseResult


class ExtractorError(RuntimeError):
    pass


class UnsupportedFormatError(ExtractorError):
    pass


class BaseExtractor(ABC):
    file_type = None

    @abstractmethod
    def extract(self, path: str, filename: str) -> ParseResult:
        raise NotImplementedError


def missing_dependency(package_name: str, file_type: str) -> ExtractorError:
    return ExtractorError(
        f"Dependency '{package_name}' is required to parse {file_type.upper()} files"
    )

