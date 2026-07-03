"""Умный многоисточниковый парсер научной базы знаний.

Единый интерфейс к внешним научным ресурсам. Каждый коннектор возвращает записи
в едином нормализованном формате; аггрегатор объединяет и дедуплицирует их.

Активные keyless-коннекторы:
  • OpenAlex          — литература + реконструированные аннотации
  • Crossref          — метаданные публикаций + аннотации (JATS)
  • Semantic Scholar  — литература + TLDR-выжимки (best-effort, часто 429 без ключа)

Гейтированные (включаются при наличии ключа):
  • Materials Project — свойства материалов (MP_API_KEY)

Расширение под NIMS MatNavi / Citrination — добавить функцию-коннектор и запись
в CONNECTORS. Интерфейс: fn(query, limit) -> list[record].
"""
import re
import httpx

from config import Config
from openalex import normalize_work, _build_excerpt


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _clean(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ""


def _dedupe_key(rec: dict) -> str:
    ref = _clean(rec.get("reference")).lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", ref)
    if doi:
        return f"doi:{doi}"
    return f"tt:{_clean(rec.get('title')).lower()[:120]}|{rec.get('year')}"


# ── OpenAlex ─────────────────────────────────────────────────────────────────
def _openalex(query: str, limit: int) -> list[dict]:
    from openalex import search_works
    records = search_works(query, per_page=limit)
    for r in records:
        r["origin"] = "openalex"
    return records


# ── Crossref ─────────────────────────────────────────────────────────────────
def _crossref(query: str, limit: int) -> list[dict]:
    params = {
        "query": query,
        "rows": max(1, min(limit, 10)),
        "select": "title,author,issued,DOI,abstract,container-title,type,URL",
    }
    if Config.CONTACT_MAILTO:
        params["mailto"] = Config.CONTACT_MAILTO
    with httpx.Client(base_url=Config.CROSSREF_API_URL, timeout=Config.EXTERNAL_TIMEOUT,
                      headers={"User-Agent": f"HypothesisFactory/1.0 (mailto:{Config.CONTACT_MAILTO})"},
                      follow_redirects=True) as client:
        resp = client.get("/works", params=params)
        resp.raise_for_status()
    items = (resp.json().get("message") or {}).get("items", [])

    out = []
    for it in items:
        title = _clean((it.get("title") or [""])[0])
        if not title:
            continue
        abstract = _strip_tags(it.get("abstract"))
        authors = []
        for a in it.get("author", []) or []:
            name = _clean(a.get("name")) or " ".join(filter(None, [_clean(a.get("given")), _clean(a.get("family"))]))
            if name:
                authors.append(name)
        author_str = ", ".join(authors[:4]) + (" et al." if len(authors) > 4 else "")
        year = None
        parts = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
        if parts and isinstance(parts[0], int):
            year = parts[0]
        doi = _clean(it.get("DOI"))
        out.append({
            "external_id": f"https://doi.org/{doi}" if doi else _clean(it.get("URL")),
            "title": title,
            "source_type": "literature",
            "authors": author_str or None,
            "year": year,
            "reference": f"https://doi.org/{doi}" if doi else _clean(it.get("URL")) or None,
            "content": abstract,
            "excerpt": _build_excerpt(abstract),
            "journal": _clean((it.get("container-title") or [""])[0]) or None,
            "work_type": _clean(it.get("type")) or None,
            "landing_page_url": _clean(it.get("URL")) or None,
            "pdf_url": None,
            "is_open_access": None,
            "origin": "crossref",
        })
    return out


# ── Semantic Scholar (best-effort) ──────────────────────────────────────────
def _semantic_scholar(query: str, limit: int) -> list[dict]:
    params = {
        "query": query,
        "limit": max(1, min(limit, 10)),
        "fields": "title,abstract,year,authors,externalIds,tldr,venue,openAccessPdf,url",
    }
    headers = {"User-Agent": "HypothesisFactory/1.0"}
    if Config.SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = Config.SEMANTIC_SCHOLAR_API_KEY
    with httpx.Client(base_url=Config.SEMANTIC_SCHOLAR_API_URL, timeout=Config.EXTERNAL_TIMEOUT,
                      headers=headers, follow_redirects=True) as client:
        resp = client.get("/graph/v1/paper/search", params=params)
        resp.raise_for_status()
    items = resp.json().get("data", []) or []

    out = []
    for it in items:
        title = _clean(it.get("title"))
        if not title:
            continue
        abstract = _clean(it.get("abstract"))
        tldr = _clean((it.get("tldr") or {}).get("text"))
        content = abstract or tldr
        authors = [_clean(a.get("name")) for a in (it.get("authors") or []) if _clean(a.get("name"))]
        author_str = ", ".join(authors[:4]) + (" et al." if len(authors) > 4 else "")
        ext = it.get("externalIds") or {}
        doi = _clean(ext.get("DOI"))
        ref = f"https://doi.org/{doi}" if doi else _clean(it.get("url"))
        out.append({
            "external_id": ref or _clean(ext.get("CorpusId")),
            "title": title,
            "source_type": "literature",
            "authors": author_str or None,
            "year": it.get("year"),
            "reference": ref or None,
            "content": content,
            "excerpt": _build_excerpt(content),
            "journal": _clean(it.get("venue")) or None,
            "work_type": "article",
            "landing_page_url": _clean(it.get("url")) or None,
            "pdf_url": _clean((it.get("openAccessPdf") or {}).get("url")) or None,
            "is_open_access": bool(it.get("openAccessPdf")),
            "tldr": tldr or None,
            "origin": "semantic_scholar",
        })
    return out


# ── Materials Project (гейтируется ключом) ──────────────────────────────────
_ELEMENT_RE = re.compile(r"\b([A-Z][a-z]?)\b")
_KNOWN_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S",
    "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga",
    "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd",
    "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "W", "Re", "Os",
    "Ir", "Pt", "Au", "Hg", "Pb", "Bi", "Nd", "Sm", "Gd", "Ta", "Hf",
}


def _materials_project(query: str, limit: int) -> list[dict]:
    """Свойства материалов из Materials Project по элементам из запроса.

    Работает только при заданном MP_API_KEY. Без ключа возвращает [] (не ошибка).
    Химические элементы извлекаются из текста запроса (Ni, Cr, Mo ...).
    """
    if not Config.MP_API_KEY:
        return []
    elements = [e for e in _ELEMENT_RE.findall(query) if e in _KNOWN_ELEMENTS]
    if not elements:
        return []
    elements = list(dict.fromkeys(elements))[:4]

    params = {
        "elements": ",".join(elements),
        "_limit": max(1, min(limit, 10)),
        "_fields": "material_id,formula_pretty,elements,band_gap,formation_energy_per_atom,"
                   "energy_above_hull,is_stable,density,symmetry",
    }
    with httpx.Client(base_url=Config.MP_API_URL, timeout=Config.EXTERNAL_TIMEOUT,
                      headers={"X-API-KEY": Config.MP_API_KEY, "User-Agent": "HypothesisFactory/1.0"},
                      follow_redirects=True) as client:
        resp = client.get("/materials/summary/", params=params)
        resp.raise_for_status()
    rows = resp.json().get("data", []) or []

    out = []
    for r in rows:
        formula = _clean(r.get("formula_pretty"))
        if not formula:
            continue
        props = [
            f"band_gap={r.get('band_gap')} эВ" if r.get("band_gap") is not None else None,
            f"E_form={r.get('formation_energy_per_atom')} эВ/ат" if r.get("formation_energy_per_atom") is not None else None,
            f"E_above_hull={r.get('energy_above_hull')} эВ/ат" if r.get("energy_above_hull") is not None else None,
            f"плотность={r.get('density')} г/см³" if r.get("density") is not None else None,
            "термодинамически стабильна" if r.get("is_stable") else None,
        ]
        content = f"Материал {formula} (Materials Project). " + "; ".join(p for p in props if p) + "."
        mid = _clean(r.get("material_id"))
        out.append({
            "external_id": mid,
            "title": f"{formula} — расчётные свойства (Materials Project)",
            "source_type": "dataset",
            "authors": "Materials Project",
            "year": None,
            "reference": f"https://materialsproject.org/materials/{mid}" if mid else None,
            "content": content,
            "excerpt": _build_excerpt(content),
            "journal": "Materials Project",
            "work_type": "dataset",
            "landing_page_url": f"https://materialsproject.org/materials/{mid}" if mid else None,
            "pdf_url": None,
            "is_open_access": True,
            "origin": "materials_project",
        })
    return out


# ── Реестр коннекторов ───────────────────────────────────────────────────────
CONNECTORS = {
    "openalex": {"label": "OpenAlex", "kind": "литература", "fn": _openalex, "keyless": True},
    "crossref": {"label": "Crossref", "kind": "литература", "fn": _crossref, "keyless": True},
    "semantic_scholar": {"label": "Semantic Scholar", "kind": "литература", "fn": _semantic_scholar, "keyless": True},
    "materials_project": {"label": "Materials Project", "kind": "свойства материалов", "fn": _materials_project,
                          "keyless": False, "needs_key": "MP_API_KEY"},
}


def _is_active(name: str) -> bool:
    meta = CONNECTORS.get(name)
    if not meta:
        return False
    if meta.get("keyless"):
        return True
    return bool(getattr(Config, meta.get("needs_key", ""), ""))


def active_connectors() -> list[dict]:
    """Список активных коннекторов (для /api/config и UI)."""
    out = []
    for name, meta in CONNECTORS.items():
        out.append({
            "name": name,
            "label": meta["label"],
            "kind": meta["kind"],
            "active": _is_active(name),
            "keyless": meta.get("keyless", False),
        })
    return out


def default_sources() -> list[str]:
    requested = [s.strip() for s in (Config.EXTERNAL_SOURCES or "").split(",") if s.strip()]
    active = [n for n in requested if _is_active(n)]
    # materials_project добавляем автоматически, если ключ есть
    if _is_active("materials_project") and "materials_project" not in active:
        active.append("materials_project")
    return active or ["openalex"]


def search_all(query: str, sources: list[str] = None, per_source_limit: int = None) -> dict:
    """Опросить несколько научных источников и объединить результаты.

    Возвращает: {records, stats: {connector: count}, errors: {connector: msg}}
    records — дедуплицированный список нормализованных записей.
    """
    query = (query or "").strip()
    if len(query) < 2:
        return {"records": [], "stats": {}, "errors": {}}

    sources = sources or default_sources()
    per_source_limit = per_source_limit or Config.OPENALEX_PER_PAGE

    records, seen, stats, errors = [], set(), {}, {}
    for name in sources:
        if not _is_active(name):
            continue
        fn = CONNECTORS[name]["fn"]
        try:
            found = fn(query, per_source_limit)
        except Exception as exc:  # noqa - любой коннектор best-effort
            errors[name] = str(exc)[:200]
            continue
        stats[name] = 0
        for rec in found:
            if not _clean(rec.get("content")):
                continue  # без содержания источник бесполезен для RAG
            key = _dedupe_key(rec)
            if key in seen:
                continue
            seen.add(key)
            records.append(rec)
            stats[name] += 1
    return {"records": records, "stats": stats, "errors": errors}
