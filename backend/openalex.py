"""Helpers for OpenAlex work search and normalization."""
from __future__ import annotations

from typing import Any

import httpx

from config import Config


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _build_excerpt(text: str, limit: int = 240) -> str:
    compact = " ".join(_clean_text(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not isinstance(inverted_index, dict):
        return ""

    tokens: list[tuple[int, str]] = []
    for token, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                tokens.append((position, token))

    if not tokens:
        return ""

    tokens.sort(key=lambda item: item[0])
    return " ".join(token for _, token in tokens)


def _format_authors(authorships: list[dict[str, Any]] | None) -> str:
    names = []
    for authorship in authorships or []:
        author = authorship.get("author") or {}
        name = _clean_text(author.get("display_name"))
        if name:
            names.append(name)

    if len(names) > 4:
        return ", ".join(names[:4]) + " et al."
    return ", ".join(names)


def _pick_locations(work: dict[str, Any]) -> tuple[str | None, str | None]:
    landing_page_url = None
    pdf_url = None
    open_access = work.get("open_access") or {}
    candidates = [
        work.get("best_oa_location"),
        work.get("primary_location"),
        *(work.get("locations") or []),
    ]

    for location in candidates:
        if not isinstance(location, dict):
            continue
        landing_page_url = landing_page_url or location.get("landing_page_url")
        pdf_url = pdf_url or location.get("pdf_url")
        source = location.get("source") or {}
        landing_page_url = landing_page_url or source.get("homepage_url")

    oa_url = open_access.get("oa_url")
    landing_page_url = landing_page_url or oa_url
    if isinstance(oa_url, str) and oa_url.lower().endswith(".pdf"):
        pdf_url = pdf_url or oa_url

    return landing_page_url, pdf_url


def normalize_work(work: dict[str, Any]) -> dict[str, Any]:
    title = _clean_text(work.get("display_name") or work.get("title"))
    abstract = _clean_text(_reconstruct_abstract(work.get("abstract_inverted_index")))
    landing_page_url, pdf_url = _pick_locations(work)
    openalex_id = _clean_text(work.get("id"))
    doi = _clean_text(work.get("doi"))
    reference = doi or landing_page_url or openalex_id
    primary_location = work.get("primary_location") or {}
    primary_source = primary_location.get("source") or {}
    journal = _clean_text(primary_source.get("display_name"))

    return {
        "external_id": openalex_id,
        "title": title,
        "source_type": "literature",
        "authors": _format_authors(work.get("authorships")),
        "year": work.get("publication_year"),
        "reference": reference,
        "content": abstract,
        "excerpt": _build_excerpt(abstract),
        "openalex_url": openalex_id or None,
        "landing_page_url": landing_page_url,
        "pdf_url": pdf_url,
        "journal": journal or None,
        "work_type": _clean_text(work.get("type")) or None,
        "is_open_access": bool((work.get("open_access") or {}).get("is_oa")),
    }


def search_works(query: str, per_page: int | None = None) -> list[dict[str, Any]]:
    cleaned_query = _clean_text(query)
    if len(cleaned_query) < 2:
        return []

    params = {
        "search": cleaned_query,
        "filter": "has_abstract:true,is_oa:true",
        "per-page": max(1, min(per_page or Config.OPENALEX_PER_PAGE, 10)),
    }
    if Config.OPENALEX_MAILTO:
        params["mailto"] = Config.OPENALEX_MAILTO

    try:
        with httpx.Client(
            base_url=Config.OPENALEX_API_URL,
            timeout=Config.OPENALEX_TIMEOUT,
            headers={"User-Agent": "HypothesisFactory/1.0"},
            follow_redirects=True,
        ) as client:
            response = client.get("/works", params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError("Не удалось получить результаты из внешнего источника") from exc

    payload = response.json()
    return [normalize_work(work) for work in payload.get("results", [])]
