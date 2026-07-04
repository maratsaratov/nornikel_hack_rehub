"""FastAPI «Фабрики гипотез»."""
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import inspect, or_, text

from config import Config
from db import db
from models import (
    Project,
    ProjectMetric,
    ProjectMembership,
    ROLE_OWNER,
    KnowledgeSource,
    Hypothesis,
    GenerationRun,
    SourceDocument,
    DocumentChunk,
    DocumentTable,
    DEFAULT_WEIGHTS,
)
from auth import (
    add_project_member,
    login_user,
    logout_user,
    register_user,
    remove_project_member,
    require_project_access,
    require_project_owner,
    require_user,
)
from engine import generate_hypotheses, suggest_weights
import llm
import reranker
import embeddings
import connectors
import export
import local_kb
from ingestion.service import (
    FileTooLargeError,
    IngestionError,
    delete_document as delete_ingested_document,
    document_preview,
    parse_document as parse_ingested_document,
    save_upload,
)


def _configure_logging():
    root_logger = logging.getLogger()
    gunicorn_logger = logging.getLogger("gunicorn.error")

    if gunicorn_logger.handlers:
        root_logger.handlers = list(gunicorn_logger.handlers)
        root_logger.setLevel(gunicorn_logger.level or logging.INFO)
    elif not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            force=True,
        )
    else:
        root_logger.setLevel(logging.INFO)


_configure_logging()
logger = logging.getLogger(__name__)


def _parse_weights(raw):
    """Веса из query (?weights=json) или из тела запроса."""
    if not raw:
        return None
    if isinstance(raw, dict):
        return {k: float(v) for k, v in raw.items()}
    try:
        return {k: float(v) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError):
        return None


def _source_key(value):
    return (value or "").strip().lower()


def _source_lookups(rows):
    by_ref = {}
    by_title = {}
    by_title_year = {}

    for source in rows:
        title_key = _source_key(source.title)
        ref_key = _source_key(source.reference)

        if ref_key and ref_key not in by_ref:
            by_ref[ref_key] = source
        if title_key and title_key not in by_title:
            by_title[title_key] = source
        if title_key and source.year is not None:
            key = (title_key, source.year)
            if key not in by_title_year:
                by_title_year[key] = source

    return by_ref, by_title_year, by_title


def _match_existing_source(candidate, by_ref, by_title_year, by_title):
    ref_key = _source_key(candidate.get("reference"))
    title_key = _source_key(candidate.get("title"))
    year = candidate.get("year")

    if ref_key and ref_key in by_ref:
        return by_ref[ref_key]
    if title_key and year is not None and (title_key, year) in by_title_year:
        return by_title_year[(title_key, year)]
    if title_key and title_key in by_title:
        return by_title[title_key]
    return None


def _mark_external_results(results, existing_rows):
    by_ref, by_title_year, by_title = _source_lookups(existing_rows)
    marked = []

    for result in results:
        existing = _match_existing_source(result, by_ref, by_title_year, by_title)
        marked.append({
            **result,
            "already_added": bool(existing),
            "existing_source_id": existing.id if existing else None,
        })

    return marked


def _parse_year(raw):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _query_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _query_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _compact_metric_value(value, limit=300):
    text_value = str(value or "").strip()
    return text_value[:limit]


def _normalize_project_metrics(raw_metrics):
    if not isinstance(raw_metrics, list):
        return []

    normalized = []
    for index, item in enumerate(raw_metrics):
        if not isinstance(item, dict):
            continue
        metric = {
            "name": _compact_metric_value(item.get("name")),
            "unit": _compact_metric_value(item.get("unit"), 120),
            "current": _compact_metric_value(item.get("current"), 120),
            "target": _compact_metric_value(item.get("target"), 120),
            "position": index,
        }
        if any((metric["name"], metric["unit"], metric["current"], metric["target"])):
            normalized.append(metric)
    return normalized


def _sync_project_metrics(project, raw_metrics):
    metrics = _normalize_project_metrics(raw_metrics)
    project.metrics.delete(synchronize_session=False)

    for metric in metrics:
        db.session.add(ProjectMetric(
            project_id=project.id,
            name=metric["name"] or "Метрика эффективности",
            unit=metric["unit"],
            current_value=metric["current"],
            target_value=metric["target"],
            position=metric["position"],
        ))

    project.kpi_metric = next((metric["name"] for metric in metrics if metric["name"]), None)


def current_user_dependency(request: Request):
    return require_user(request)


def _require_source_access(user, source_id: int):
    source = db.session.get(KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    require_project_access(user, source.project_id)
    return source


def _require_document_access(user, document_id: int):
    document = db.session.get(SourceDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    require_project_access(user, document.project_id)
    return document


def _require_hypothesis_access(user, hypothesis_id: int):
    hypothesis = db.session.get(Hypothesis, hypothesis_id)
    if not hypothesis:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    require_project_access(user, hypothesis.project_id)
    return hypothesis


def _require_run_access(user, run_id: int):
    run = db.session.get(GenerationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    require_project_access(user, run.project_id)
    return run


def _acquire_knowledge(project, topic, sources=None, limit=None, dry_run=False, max_import=12):
    """«Умный парсер»: найти по теме внешние научные источники и импортировать в базу."""
    found = connectors.search_all(topic, sources=sources, per_source_limit=limit)
    records = found["records"]
    existing = project.sources.all()
    marked = _mark_external_results(records, existing)

    imported = []
    if not dry_run:
        by_ref, by_ty, by_t = _source_lookups(existing)
        seen = set()
        for rec in records:
            if len(imported) >= max_import:
                break
            title = (rec.get("title") or "").strip()
            content = (rec.get("content") or "").strip()
            if not (title and content):
                continue
            cand = {"title": title, "year": _parse_year(rec.get("year")),
                    "reference": rec.get("reference")}
            if _match_existing_source(cand, by_ref, by_ty, by_t):
                continue
            key = _source_key(rec.get("reference")) or _source_key(title)
            if key in seen:
                continue
            seen.add(key)
            s = KnowledgeSource(
                project_id=project.id,
                title=title[:400],
                content=content,
                source_type=rec.get("source_type", "literature"),
                origin=rec.get("origin", "external"),
                authors=(rec.get("authors") or None),
                year=_parse_year(rec.get("year")),
                reference=(rec.get("reference") or None),
            )
            db.session.add(s)
            imported.append(s)
        if imported:
            db.session.commit()

    return {
        "topic": topic,
        "found": len(records),
        "stats": found["stats"],
        "errors": found["errors"],
        "imported_count": len(imported),
        "imported": [s.to_dict(with_content=False) for s in imported],
        "results": marked if dry_run else None,
    }


def _ensure_columns():
    """Лёгкие миграции: добавить недостающие колонки в существующие таблицы."""
    wanted = {
        "projects": {"created_by_id": "INTEGER"},
        "knowledge_sources": {"origin": "VARCHAR(40)"},
        "hypotheses": {"goal_link": "TEXT"},
        "generation_runs": {
            "weight_mode": "VARCHAR(20)",
            "weight_rationale": "TEXT",
            "topic": "VARCHAR(400)",
            "stages": "JSON",
            "rerank_usage": "JSON",
        },
    }
    for table, cols in wanted.items():
        try:
            existing = {c["name"] for c in inspect(db.engine).get_columns(table)}
        except Exception:  # noqa - таблицы может не быть
            continue
        for col, coltype in cols.items():
            if col in existing:
                continue
            try:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                db.session.commit()
            except Exception:  # noqa - уже добавлена другим воркером/прошлым запуском
                db.session.rollback()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_app(Config.SQLALCHEMY_DATABASE_URI, Config.SQLALCHEMY_ENGINE_OPTIONS)
    db.create_all()
    _ensure_columns()
    kb_status = local_kb.status()
    if kb_status["loaded"]:
        logger.info(
            "Local knowledge loaded from %s (%s files, %s sources).",
            kb_status["directory"],
            kb_status["file_count"],
            kb_status["source_count"],
        )
    elif kb_status["errors"]:
        logger.warning("Local knowledge library has load errors: %s", kb_status["errors"])
    if Config.SEED_DEMO:
        try:
            from seed import seed_if_empty
            if seed_if_empty():
                logger.info("Демо-база знаний засеяна.")
        except Exception as e:  # noqa
            logger.warning("Не удалось засеять демо-данные: %s", e)
    yield


app = FastAPI(title="Hypothesis Factory", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def db_session_teardown(request: Request, call_next):
    try:
        return await call_next(request)
    finally:
        db.session.remove()


@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > Config.MAX_UPLOAD_BYTES:
                    return JSONResponse(
                        {"error": f"File is too large. Maximum upload size is {Config.MAX_UPLOAD_MB} MB"},
                        status_code=413,
                    )
            except ValueError:
                pass
    return await call_next(request)


# ── Health / config ─────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    kb_status = local_kb.status()
    return {
        "status": "ok",
        "model": Config.OPENAI_MODEL,
        "local_knowledge": {
            "enabled": kb_status["enabled"],
            "loaded": kb_status["loaded"],
            "file_count": kb_status["file_count"],
            "source_count": kb_status["source_count"],
        },
    }


@app.get("/api/health/llm")
def health_llm():
    return llm.ping()


@app.get("/api/health/rerank")
def health_rerank():
    return reranker.ping()


@app.get("/api/health/embed")
def health_embed():
    return embeddings.ping()


@app.get("/api/config")
def get_config():
    return {
        "model": Config.OPENAI_MODEL,
        "rerank_model": Config.RERANK_MODEL,
        "rerank_enabled": reranker.available(),
        "embed_model": Config.EMBED_MODEL,
        "embed_enabled": embeddings.available(),
        "retrieval": "hybrid (BM25 + bge-m3) → RRF → rerank" if embeddings.available()
                     else "BM25 → rerank",
        "default_weights": DEFAULT_WEIGHTS,
        "weight_modes": ["expert", "model", "default"],
        "connectors": connectors.active_connectors(),
        "default_sources": connectors.default_sources(),
        "local_knowledge": local_kb.status(),
        "max_upload_mb": Config.MAX_UPLOAD_MB,
        "supported_document_types": ["pdf", "docx", "xlsx", "csv", "txt", "png", "jpg", "jpeg"],
    }


# ── Projects ────────────────────────────────────────────────────────────
@app.post("/api/auth/register", status_code=201)
def auth_register(d: dict = Body(default={})):
    return register_user(d)


@app.post("/api/auth/login")
def auth_login(d: dict = Body(default={})):
    return login_user(d)


@app.get("/api/auth/me")
def auth_me(user=Depends(current_user_dependency)):
    return user.to_dict()


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    return logout_user(request)


@app.get("/api/projects")
def list_projects(user=Depends(current_user_dependency)):
    memberships = (
        ProjectMembership.query.filter_by(user_id=user.id)
        .join(Project)
        .order_by(Project.created_at.desc())
        .all()
    )
    return [m.project.to_dict(m.role) for m in memberships if m.project]


@app.post("/api/projects", status_code=201)
def create_project(d: dict = Body(default={}), user=Depends(current_user_dependency)):
    if not (d.get("title") and d.get("kpi_target")):
        return JSONResponse({"error": "Поля title и kpi_target обязательны"}, status_code=400)
    p = Project(
        created_by_id=user.id,
        title=d["title"].strip(),
        kpi_target=d["kpi_target"].strip(),
        kpi_metric=d.get("kpi_metric"),
        kpi_direction=d.get("kpi_direction", "increase"),
        domain=d.get("domain"),
        constraints=d.get("constraints"),
    )
    db.session.add(p)
    db.session.flush()
    if "metrics" in d:
        _sync_project_metrics(p, d.get("metrics"))
    elif d.get("kpi_metric"):
        _sync_project_metrics(p, [{"name": d.get("kpi_metric")}])
    db.session.add(ProjectMembership(project_id=p.id, user_id=user.id, role=ROLE_OWNER))
    db.session.commit()
    return p.to_dict(ROLE_OWNER)


@app.get("/api/projects/{pid}")
def get_project(pid: int, user=Depends(current_user_dependency)):
    p, membership = require_project_access(user, pid)
    return p.to_dict(membership.role)


@app.put("/api/projects/{pid}")
def update_project(pid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    p, membership = require_project_owner(user, pid)
    for f in ("title", "kpi_target", "kpi_metric", "kpi_direction", "domain", "constraints"):
        if f in d:
            setattr(p, f, d[f])
    if "metrics" in d:
        _sync_project_metrics(p, d.get("metrics"))
    db.session.commit()
    return p.to_dict(membership.role)


@app.delete("/api/projects/{pid}")
def delete_project(pid: int, user=Depends(current_user_dependency)):
    p, _membership = require_project_owner(user, pid)
    db.session.delete(p)
    db.session.commit()
    return {"deleted": pid}


@app.get("/api/projects/{pid}/members")
def list_project_members(pid: int, user=Depends(current_user_dependency)):
    p, _membership = require_project_access(user, pid)
    rows = p.memberships.all()
    rows.sort(key=lambda m: (m.role != ROLE_OWNER, m.user.username if m.user else ""))
    return [m.to_dict() for m in rows]


@app.post("/api/projects/{pid}/members", status_code=201)
def invite_project_member(pid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    p, _membership = require_project_owner(user, pid)
    membership = add_project_member(p, d.get("username"))
    return membership.to_dict()


@app.delete("/api/projects/{pid}/members/{user_id}")
def delete_project_member(pid: int, user_id: int, user=Depends(current_user_dependency)):
    p, _membership = require_project_owner(user, pid)
    return remove_project_member(p, user_id)


# ── Knowledge sources ───────────────────────────────────────────────────
@app.get("/api/projects/{pid}/sources")
def list_sources(pid: int, user=Depends(current_user_dependency)):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)
    rows = p.sources.order_by(KnowledgeSource.created_at.desc()).all()
    return [s.to_dict(with_content=False) for s in rows]


@app.get("/api/projects/{pid}/sources/search")
def search_sources(
    pid: int,
    q: str = Query(""),
    limit: int | None = Query(None),
    source: list[str] = Query(default=[]),
    user=Depends(current_user_dependency),
):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)

    query = (q or "").strip()
    page_limit = max(1, min(int(limit or Config.OPENALEX_PER_PAGE), 10))
    if len(query) < 2:
        return {
            "query": query,
            "local": [],
            "external": [],
            "external_error": None,
        }

    pattern = f"%{query}%"
    local_rows = (
        p.sources
        .filter(or_(
            KnowledgeSource.title.ilike(pattern),
            KnowledgeSource.content.ilike(pattern),
            KnowledgeSource.authors.ilike(pattern),
            KnowledgeSource.reference.ilike(pattern),
        ))
        .order_by(KnowledgeSource.created_at.desc())
        .limit(page_limit)
        .all()
    )
    existing_rows = p.sources.all()

    sources = source or None
    found = connectors.search_all(query, sources=sources, per_source_limit=page_limit)
    external = _mark_external_results(found["records"], existing_rows)
    external_error = None
    if not external and found["errors"]:
        external_error = "; ".join(f"{k}: {v}" for k, v in found["errors"].items())

    return {
        "query": query,
        "local": [s.to_dict(with_content=False) for s in local_rows],
        "external": external,
        "external_stats": found["stats"],
        "external_errors": found["errors"],
        "external_error": external_error,
    }


@app.post("/api/projects/{pid}/sources", status_code=201)
def add_source(pid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)
    if not (d.get("title") and d.get("content")):
        return JSONResponse({"error": "Поля title и content обязательны"}, status_code=400)
    s = KnowledgeSource(
        project_id=pid,
        title=d["title"].strip(),
        content=d["content"].strip(),
        source_type=d.get("source_type", "literature"),
        origin="manual",
        authors=d.get("authors"),
        year=d.get("year"),
        reference=d.get("reference"),
    )
    db.session.add(s)
    db.session.commit()
    return s.to_dict(with_content=False)


@app.post("/api/projects/{pid}/sources/import-openalex")
def import_openalex_source(pid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)

    title = (d.get("title") or "").strip()
    content = (d.get("content") or "").strip()
    if not (title and content):
        return JSONResponse({"error": "Для импорта нужны title и content"}, status_code=400)

    year = _parse_year(d.get("year"))
    reference = (d.get("reference") or "").strip() or (d.get("external_id") or "").strip() or None
    authors = (d.get("authors") or "").strip() or None

    existing_rows = p.sources.all()
    existing = _match_existing_source(
        {"title": title, "year": year, "reference": reference},
        *_source_lookups(existing_rows),
    )
    if existing:
        return JSONResponse({"created": False, "source": existing.to_dict(with_content=False)})

    s = KnowledgeSource(
        project_id=pid,
        title=title,
        content=content,
        source_type="literature",
        origin="openalex",
        authors=authors,
        year=year,
        reference=reference,
    )
    db.session.add(s)
    db.session.commit()
    return JSONResponse({"created": True, "source": s.to_dict(with_content=False)}, status_code=201)


@app.get("/api/sources/{sid}")
def get_source(sid: int, user=Depends(current_user_dependency)):
    _require_source_access(user, sid)
    s = db.session.get(KnowledgeSource, sid)
    if not s:
        return JSONResponse({"error": "Источник не найден"}, status_code=404)
    return s.to_dict(with_content=True)


@app.post("/api/projects/{pid}/knowledge/acquire")
def acquire_knowledge(pid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)
    topic = (d.get("topic") or d.get("q") or "").strip()
    if not topic:
        topic = " ".join(filter(None, [p.kpi_target, p.domain]))[:300]
    try:
        result = _acquire_knowledge(
            p, topic,
            sources=d.get("sources"),
            limit=d.get("limit"),
            dry_run=bool(d.get("preview")),
            max_import=int(d.get("max_import", 12)),
        )
    except Exception as e:  # noqa
        return JSONResponse({"error": f"Ошибка поиска источников: {e}"}, status_code=502)
    return result


@app.post("/api/projects/{pid}/weights/suggest")
def weights_suggest(pid: int, user=Depends(current_user_dependency)):
    require_project_access(user, pid)
    try:
        return suggest_weights(pid)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:  # noqa
        return JSONResponse({"error": f"Не удалось предложить веса: {e}"}, status_code=502)


@app.put("/api/sources/{sid}")
def update_source(sid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    _require_source_access(user, sid)
    s = db.session.get(KnowledgeSource, sid)
    if not s:
        return JSONResponse({"error": "Источник не найден"}, status_code=404)
    for f in ("title", "content", "source_type", "authors", "year", "reference"):
        if f in d:
            setattr(s, f, _parse_year(d[f]) if f == "year" else d[f])
    db.session.commit()
    return s.to_dict(with_content=False)


@app.delete("/api/sources/{sid}")
def delete_source(sid: int, user=Depends(current_user_dependency)):
    _require_source_access(user, sid)
    s = db.session.get(KnowledgeSource, sid)
    if not s:
        return JSONResponse({"error": "Источник не найден"}, status_code=404)
    db.session.delete(s)
    db.session.commit()
    return {"deleted": sid}


@app.get("/api/projects/{pid}/documents")
def list_documents(pid: int, user=Depends(current_user_dependency)):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    rows = p.documents.order_by(SourceDocument.created_at.desc()).all()
    return [document.to_dict(with_raw_text=False) for document in rows]


@app.post("/api/projects/{pid}/documents", status_code=201)
def upload_document(
    pid: int,
    file: UploadFile = File(...),
    parse: str | None = Query(None),
    user=Depends(current_user_dependency),
):
    require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    try:
        document = save_upload(pid, file)
    except FileTooLargeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=413)
    except IngestionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    parse_run = None
    if _query_bool(parse, default=False):
        document, parse_run = parse_ingested_document(document.id)

    payload = {"document": document.to_dict(with_raw_text=False)}
    if parse_run:
        payload["parse_run"] = parse_run.to_dict()
    return payload


@app.get("/api/documents/{did}")
def get_document(did: int, raw: str | None = Query(None), user=Depends(current_user_dependency)):
    _require_document_access(user, did)
    document = db.session.get(SourceDocument, did)
    if not document:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    return document.to_dict(with_raw_text=_query_bool(raw, default=False))


@app.post("/api/documents/{did}/parse")
def parse_document(did: int, user=Depends(current_user_dependency)):
    _require_document_access(user, did)
    document = db.session.get(SourceDocument, did)
    if not document:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    document, parse_run = parse_ingested_document(did)
    status_code = 200 if parse_run.status == "parsed" else 422
    return JSONResponse({
        "document": document.to_dict(with_raw_text=False),
        "parse_run": parse_run.to_dict(),
    }, status_code=status_code)


@app.get("/api/documents/{did}/chunks")
def list_document_chunks(
    did: int,
    limit: int | None = Query(None),
    offset: int | None = Query(None),
    user=Depends(current_user_dependency),
):
    _require_document_access(user, did)
    document = db.session.get(SourceDocument, did)
    if not document:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    page_limit = _query_int(limit, 100, minimum=1, maximum=500)
    page_offset = _query_int(offset, 0, minimum=0)
    query = document.chunks.order_by(DocumentChunk.chunk_index.asc())
    return {
        "document_id": did,
        "count": query.count(),
        "items": [chunk.to_dict() for chunk in query.offset(page_offset).limit(page_limit).all()],
    }


@app.get("/api/documents/{did}/tables")
def list_document_tables(
    did: int,
    limit: int | None = Query(None),
    offset: int | None = Query(None),
    user=Depends(current_user_dependency),
):
    _require_document_access(user, did)
    document = db.session.get(SourceDocument, did)
    if not document:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    page_limit = _query_int(limit, 50, minimum=1, maximum=200)
    page_offset = _query_int(offset, 0, minimum=0)
    query = document.tables.order_by(DocumentTable.id.asc())
    return {
        "document_id": did,
        "count": query.count(),
        "items": [table.to_dict() for table in query.offset(page_offset).limit(page_limit).all()],
    }


@app.get("/api/documents/{did}/preview")
def preview_document(did: int, user=Depends(current_user_dependency)):
    _require_document_access(user, did)
    document = db.session.get(SourceDocument, did)
    if not document:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    return document_preview(document)


@app.delete("/api/documents/{did}")
def delete_document_endpoint(did: int, user=Depends(current_user_dependency)):
    _require_document_access(user, did)
    document = db.session.get(SourceDocument, did)
    if not document:
        return JSONResponse({"error": "Document not found"}, status_code=404)
    delete_ingested_document(document)
    return {"deleted": did}


# ── Generation ──────────────────────────────────────────────────────────
@app.post("/api/projects/{pid}/generate", status_code=201)
def generate(pid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)

    n = max(1, min(int(d.get("n", 5)), 10))
    top_k = max(1, min(int(d.get("top_k", 6)), 12))
    weights = _parse_weights(d.get("weights"))
    weight_mode = d.get("weight_mode") or ("expert" if weights else "default")
    topic = (d.get("topic") or "").strip() or None
    use_rerank = bool(d.get("use_rerank", True))
    candidate_pool = d.get("candidate_pool")
    if candidate_pool is not None:
        candidate_pool = max(4, min(int(candidate_pool), 60))

    acquired = None
    try:
        if d.get("acquire_external"):
            acq_topic = topic or " ".join(filter(None, [p.kpi_target, p.domain]))[:300]
            acquired = _acquire_knowledge(
                p, acq_topic, sources=d.get("sources"),
                limit=d.get("acquire_limit"), max_import=int(d.get("max_import", 12)),
            )
        run, hyps = generate_hypotheses(
            pid, n=n, top_k=top_k, weights=weights, weight_mode=weight_mode,
            topic=topic, use_rerank=use_rerank, candidate_pool=candidate_pool,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    except Exception as e:  # noqa
        return JSONResponse({"error": f"Внутренняя ошибка генерации: {e}"}, status_code=500)

    resp = {"run": run, "hypotheses": hyps}
    if acquired is not None:
        resp["acquired"] = acquired
    return resp


# ── Hypotheses ──────────────────────────────────────────────────────────
@app.get("/api/projects/{pid}/hypotheses")
def list_hypotheses(
    pid: int,
    weights: str | None = Query(None),
    status: str | None = Query(None),
    user=Depends(current_user_dependency),
):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)
    parsed_weights = _parse_weights(weights) or DEFAULT_WEIGHTS
    q = p.hypotheses
    if status:
        q = q.filter(Hypothesis.status == status)
    rows = q.all()
    out = [h.to_dict(parsed_weights) for h in rows]
    out.sort(key=lambda x: x["composite"], reverse=True)
    return out


@app.get("/api/projects/{pid}/hypotheses/export")
def export_hypotheses(
    pid: int,
    format: str = Query("md", alias="format"),
    weights: str | None = Query(None),
    user=Depends(current_user_dependency),
):
    p, membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)
    fmt = (format or "pdf").lower()
    parsed_weights = _parse_weights(weights) or DEFAULT_WEIGHTS
    hyps = [h.to_dict(parsed_weights) for h in p.hypotheses.all()]
    hyps.sort(key=lambda x: x["composite"], reverse=True)
    project = p.to_dict(membership.role)

    def _file(content, media_type, ext):
        return Response(
            content=content, media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="project_{pid}_hypotheses.{ext}"'},
        )

    if fmt == "json":
        return _file(export.to_json(project, hyps, parsed_weights), "application/json", "json")
    if fmt == "csv":
        return _file(export.to_csv(hyps), "text/csv", "csv")
    if fmt == "md":
        return _file(export.to_markdown(project, hyps, parsed_weights), "text/markdown", "md")
    if fmt == "docx":
        try:
            data = export.to_docx(project, hyps, parsed_weights)
        except Exception as e:  # noqa
            return JSONResponse({"error": f"Не удалось сформировать DOCX: {e}"}, status_code=500)
        return _file(data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx")
    if fmt == "pdf":
        try:
            data = export.to_pdf(project, hyps, parsed_weights)
        except export.ExportError as e:
            return JSONResponse({"error": str(e)}, status_code=501)
        except Exception as e:  # noqa
            return JSONResponse({"error": f"Не удалось сформировать PDF: {e}"}, status_code=500)
        return _file(data, "application/pdf", "pdf")
    return JSONResponse({"error": f"Неизвестный формат: {fmt}"}, status_code=400)


@app.patch("/api/hypotheses/{hid}")
def update_hypothesis(hid: int, d: dict = Body(default={}), user=Depends(current_user_dependency)):
    _require_hypothesis_access(user, hid)
    h = db.session.get(Hypothesis, hid)
    if not h:
        return JSONResponse({"error": "Гипотеза не найдена"}, status_code=404)
    if "status" in d and d["status"] in ("proposed", "accepted", "rejected", "review"):
        h.status = d["status"]
    if "expert_notes" in d:
        h.expert_notes = d["expert_notes"]
    if "expert_scores" in d:
        cur = dict(h.expert_scores or {})
        for k, v in (d["expert_scores"] or {}).items():
            if k in ("novelty", "value", "feasibility", "risk"):
                if v is None:
                    cur.pop(k, None)
                else:
                    cur[k] = max(0, min(100, float(v)))
        h.expert_scores = cur or None
    for f in ("statement", "rationale", "mechanism", "validation"):
        if f in d:
            setattr(h, f, d[f])
    db.session.commit()
    parsed_weights = _parse_weights(d.get("weights")) or DEFAULT_WEIGHTS
    return h.to_dict(parsed_weights)


@app.delete("/api/hypotheses/{hid}")
def delete_hypothesis(hid: int, user=Depends(current_user_dependency)):
    _require_hypothesis_access(user, hid)
    h = db.session.get(Hypothesis, hid)
    if not h:
        return JSONResponse({"error": "Гипотеза не найдена"}, status_code=404)
    db.session.delete(h)
    db.session.commit()
    return {"deleted": hid}


# ── Runs (аудит/прозрачность) ───────────────────────────────────────────
@app.get("/api/projects/{pid}/runs")
def list_runs(pid: int, user=Depends(current_user_dependency)):
    p, _membership = require_project_access(user, pid)
    p = db.session.get(Project, pid)
    if not p:
        return JSONResponse({"error": "Проект не найден"}, status_code=404)
    rows = p.runs.order_by(GenerationRun.created_at.desc()).all()
    return [r.to_dict() for r in rows]


@app.get("/api/runs/{rid}")
def get_run(rid: int, user=Depends(current_user_dependency)):
    _require_run_access(user, rid)
    r = db.session.get(GenerationRun, rid)
    if not r:
        return JSONResponse({"error": "Запуск не найден"}, status_code=404)
    return r.to_dict()
