from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import Config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LocalKnowledgeSource:
    id: str
    title: str
    content: str
    source_type: str = "library_note"
    origin: str = "local_lib"
    authors: str | None = None
    year: int | None = None
    reference: str | None = None


_CACHE_SIGNATURE: tuple | None = None
_CACHE_SOURCES: list[LocalKnowledgeSource] = []
_CACHE_STATUS: dict[str, Any] = {
    "enabled": False,
    "loaded": False,
    "directory": "",
    "file_count": 0,
    "files": [],
    "source_count": 0,
    "source_types": {},
    "errors": [],
}


def get_sources() -> list[LocalKnowledgeSource]:
    _refresh_cache()
    return list(_CACHE_SOURCES)


def status() -> dict[str, Any]:
    _refresh_cache()
    return dict(_CACHE_STATUS)


def _refresh_cache(force: bool = False) -> None:
    global _CACHE_SIGNATURE, _CACHE_SOURCES, _CACHE_STATUS

    kb_dir = Path(Config.LOCAL_KB_DIR)
    files = sorted(kb_dir.glob("*.json")) if Config.LOCAL_KB_ENABLED and kb_dir.exists() else []
    signature = tuple((str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size) for path in files)

    if not force and signature == _CACHE_SIGNATURE:
        return

    errors: list[dict[str, str]] = []
    sources: list[LocalKnowledgeSource] = []

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            sources.extend(_build_sources_from_file(path, payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load local knowledge file %s: %s", path, exc)
            errors.append({"file": path.name, "error": str(exc)[:200]})

    _CACHE_SIGNATURE = signature
    _CACHE_SOURCES = sources
    _CACHE_STATUS = {
        "enabled": bool(Config.LOCAL_KB_ENABLED),
        "loaded": bool(sources),
        "directory": str(kb_dir),
        "file_count": len(files),
        "files": [path.name for path in files],
        "source_count": len(sources),
        "source_types": dict(Counter(src.source_type for src in sources)),
        "errors": errors,
    }


def _build_sources_from_file(path: Path, payload: dict[str, Any]) -> list[LocalKnowledgeSource]:
    sources: list[LocalKnowledgeSource] = []
    title = _clean_text(payload.get("title")) or path.stem
    note = _clean_text(payload.get("note"))

    playbook = payload.get("retrieval_playbook") or {}
    if isinstance(playbook, dict):
        playbook_text = _compose_text(
            _section("Corpus", title),
            _section("Note", note),
            _section("Goal", playbook.get("goal")),
            _list_section("Selection rules", playbook.get("selection_rules")),
            _list_section("Log fields", playbook.get("log_fields")),
        )
        if playbook_text:
            sources.append(
                _make_source(
                    path,
                    "playbook",
                    f"{title}: retrieval playbook",
                    playbook_text,
                    "playbook",
                )
            )

    taxonomy = payload.get("domain_taxonomy") or {}
    if isinstance(taxonomy, dict):
        taxonomy_text = _compose_text(
            _section("Corpus", title),
            _list_section("Assets", taxonomy.get("assets")),
            _list_section("Media", taxonomy.get("media")),
            _list_section("Failure modes", taxonomy.get("failure_modes")),
            _list_section("Action classes", taxonomy.get("action_classes")),
        )
        if taxonomy_text:
            sources.append(
                _make_source(
                    path,
                    "taxonomy",
                    f"{title}: domain taxonomy",
                    taxonomy_text,
                    "taxonomy",
                )
            )

    for entry in _as_list(payload.get("sources")):
        built = _build_reference_source(path, entry)
        if built:
            sources.append(built)

    for entry in _as_list(payload.get("asset_profiles")):
        built = _build_asset_profile(path, entry)
        if built:
            sources.append(built)

    for entry in _as_list(payload.get("failure_modes")):
        built = _build_failure_mode(path, entry)
        if built:
            sources.append(built)

    for entry in _as_list(payload.get("process_signals")):
        built = _build_process_signal(path, entry)
        if built:
            sources.append(built)

    for entry in _as_list(payload.get("retrieval_examples")):
        built = _build_retrieval_example(path, entry)
        if built:
            sources.append(built)

    return [src for src in sources if src.title and src.content]


def _build_reference_source(path: Path, entry: dict[str, Any]) -> LocalKnowledgeSource | None:
    source_id = _clean_text(entry.get("source_id")) or entry.get("title") or "reference"
    key_passages = []
    for passage in _as_list(entry.get("key_passages")):
        block = _compose_text(
            _section("Heading", passage.get("heading")),
            _section("Text", passage.get("text")),
            _inline_list("Signals", passage.get("signals")),
            _inline_list("Use when", passage.get("use_when"), separator="; "),
        )
        if block:
            key_passages.append(block)

    content = _compose_text(
        _section("Summary", entry.get("summary")),
        _section("Content", entry.get("content")),
        _inline_list("Tags", entry.get("tags")),
        _joined_blocks("Key passages", key_passages),
    )
    if not content:
        return None

    return _make_source(
        path,
        source_id,
        _clean_text(entry.get("title")) or source_id,
        content,
        _clean_text(entry.get("source_type")) or "literature",
        authors=_clean_text(entry.get("authors")) or None,
        year=_safe_year(entry.get("year")),
        reference=_clean_text(entry.get("reference")) or _library_reference(path),
    )


def _build_asset_profile(path: Path, entry: dict[str, Any]) -> LocalKnowledgeSource | None:
    asset_id = _clean_text(entry.get("asset_id")) or entry.get("asset_type") or "asset"
    title = _clean_text(entry.get("asset_type")) or asset_id
    content = _compose_text(
        _list_section("Weak zones", entry.get("weak_zones")),
        _list_section("Monitoring focus", entry.get("monitoring_focus")),
    )
    if not content:
        return None
    return _make_source(path, asset_id, title, content, "asset_profile")


def _build_failure_mode(path: Path, entry: dict[str, Any]) -> LocalKnowledgeSource | None:
    item_id = _clean_text(entry.get("failure_mode_id")) or entry.get("name") or "failure-mode"
    title = _clean_text(entry.get("name")) or item_id
    content = _compose_text(
        _list_section("Diagnostic signals", entry.get("diagnostic_signals")),
        _list_section("Common triggers", entry.get("common_triggers")),
    )
    if not content:
        return None
    return _make_source(path, item_id, title, content, "failure_mode")


def _build_process_signal(path: Path, entry: dict[str, Any]) -> LocalKnowledgeSource | None:
    item_id = _clean_text(entry.get("signal_id")) or entry.get("name") or "process-signal"
    title = _clean_text(entry.get("name")) or item_id
    content = _section("Why important", entry.get("why_important"))
    if not content:
        return None
    return _make_source(path, item_id, title, content, "process_signal")


def _build_retrieval_example(path: Path, entry: dict[str, Any]) -> LocalKnowledgeSource | None:
    item_id = _clean_text(entry.get("example_id")) or "retrieval-example"
    query = _clean_text(entry.get("query"))
    selection_log = []
    for log_item in _as_list(entry.get("selection_log")):
        block = _compose_text(
            _section("Passage", log_item.get("passage_id")),
            _section("Why selected", log_item.get("why_selected")),
        )
        if block:
            selection_log.append(block)

    rejected = []
    for rejected_item in _as_list(entry.get("rejected_passages")):
        block = _compose_text(
            _section("Passage", rejected_item.get("passage_id")),
            _section("Why rejected", rejected_item.get("why_rejected")),
        )
        if block:
            rejected.append(block)

    content = _compose_text(
        _section("Query", query),
        _section("Project context", entry.get("project_context")),
        _inline_list("Selected passages", entry.get("selected_passages")),
        _joined_blocks("Selection log", selection_log),
        _joined_blocks("Rejected passages", rejected),
        _section("Synthesis hint", entry.get("synthesis_hint")),
        _list_section("Open risks", entry.get("open_risks")),
        _list_section("Next checks", entry.get("next_checks")),
    )
    if not content:
        return None

    short_query = query[:120] + ("..." if len(query) > 120 else "")
    return _make_source(
        path,
        item_id,
        f"Retrieval example: {short_query or item_id}",
        content,
        "retrieval_example",
    )


def _make_source(
    path: Path,
    raw_id: str,
    title: str,
    content: str,
    source_type: str,
    *,
    authors: str | None = None,
    year: int | None = None,
    reference: str | None = None,
) -> LocalKnowledgeSource:
    return LocalKnowledgeSource(
        id=f"lib:{path.stem}:{_clean_text(raw_id) or source_type}",
        title=(title or source_type)[:400],
        content=content,
        source_type=source_type,
        origin="local_lib",
        authors=authors,
        year=year,
        reference=reference or _library_reference(path),
    )


def _library_reference(path: Path) -> str:
    return f"lib/{path.name}"


def _compose_text(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _section(label: str, value: Any) -> str:
    text = _clean_text(value)
    return f"{label}: {text}" if text else ""


def _inline_list(label: str, values: Any, separator: str = ", ") -> str:
    cleaned = [_clean_text(item) for item in _as_list(values)]
    cleaned = [item for item in cleaned if item]
    return f"{label}: {separator.join(cleaned)}" if cleaned else ""


def _list_section(label: str, values: Any) -> str:
    cleaned = [_clean_text(item) for item in _as_list(values)]
    cleaned = [item for item in cleaned if item]
    if not cleaned:
        return ""
    return f"{label}:\n" + "\n".join(f"- {item}" for item in cleaned)


def _joined_blocks(label: str, blocks: list[str]) -> str:
    blocks = [block for block in blocks if block]
    if not blocks:
        return ""
    return f"{label}:\n" + "\n\n".join(blocks)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(value).split())


def _safe_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
