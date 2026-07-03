"""Flask API «Фабрики гипотез»."""
import json
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from sqlalchemy import inspect, or_, text

from config import Config
from db import db
from models import Project, KnowledgeSource, Hypothesis, GenerationRun, DEFAULT_WEIGHTS, composite_score
from engine import generate_hypotheses, suggest_weights
import llm
import reranker
import connectors
import export


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


def _acquire_knowledge(project, topic, sources=None, limit=None, dry_run=False, max_import=12):
    """«Умный парсер»: найти по теме внешние научные источники и импортировать в базу.

    Идея: на этапе поиска — широкий recall из нескольких научных ресурсов; отбор
    precision происходит позже в RAG+reranker при генерации. Дедуплицируем против
    уже имеющихся источников проекта.
    """
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
    """Лёгкие миграции: добавить недостающие колонки в существующие таблицы.

    db.create_all() создаёт только отсутствующие ТАБЛИЦЫ, но не колонки, поэтому
    новые поля (origin, goal_link, RAG/rerank-поля прогонов) добавляем вручную.
    """
    wanted = {
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
            # Каждая колонка — в своей транзакции. try/except делает миграцию
            # идемпотентной и безопасной к гонке воркеров gunicorn (DuplicateColumn).
            try:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                db.session.commit()
            except Exception:  # noqa - уже добавлена другим воркером/прошлым запуском
                db.session.rollback()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_columns()
        if Config.SEED_DEMO:
            try:
                from seed import seed_if_empty
                if seed_if_empty():
                    app.logger.info("Демо-база знаний засеяна.")
            except Exception as e:  # noqa
                app.logger.warning("Не удалось засеять демо-данные: %s", e)

    # ── Health / config ─────────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "model": Config.OPENAI_MODEL})

    @app.get("/api/health/llm")
    def health_llm():
        return jsonify(llm.ping())

    @app.get("/api/health/rerank")
    def health_rerank():
        return jsonify(reranker.ping())

    @app.get("/api/config")
    def get_config():
        return jsonify({
            "model": Config.OPENAI_MODEL,
            "rerank_model": Config.RERANK_MODEL,
            "rerank_enabled": reranker.available(),
            "default_weights": DEFAULT_WEIGHTS,
            "weight_modes": ["expert", "model", "default"],
            "connectors": connectors.active_connectors(),
            "default_sources": connectors.default_sources(),
        })

    # ── Projects ────────────────────────────────────────────────────────────
    @app.get("/api/projects")
    def list_projects():
        rows = Project.query.order_by(Project.created_at.desc()).all()
        return jsonify([p.to_dict() for p in rows])

    @app.post("/api/projects")
    def create_project():
        d = request.get_json(force=True) or {}
        if not (d.get("title") and d.get("kpi_target")):
            return jsonify({"error": "Поля title и kpi_target обязательны"}), 400
        p = Project(
            title=d["title"].strip(),
            kpi_target=d["kpi_target"].strip(),
            kpi_metric=d.get("kpi_metric"),
            kpi_direction=d.get("kpi_direction", "increase"),
            domain=d.get("domain"),
            constraints=d.get("constraints"),
        )
        db.session.add(p)
        db.session.commit()
        return jsonify(p.to_dict()), 201

    @app.get("/api/projects/<int:pid>")
    def get_project(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        return jsonify(p.to_dict())

    @app.put("/api/projects/<int:pid>")
    def update_project(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        d = request.get_json(force=True) or {}
        for f in ("title", "kpi_target", "kpi_metric", "kpi_direction", "domain", "constraints"):
            if f in d:
                setattr(p, f, d[f])
        db.session.commit()
        return jsonify(p.to_dict())

    @app.delete("/api/projects/<int:pid>")
    def delete_project(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        db.session.delete(p)
        db.session.commit()
        return jsonify({"deleted": pid})

    # ── Knowledge sources ───────────────────────────────────────────────────
    @app.get("/api/projects/<int:pid>/sources")
    def list_sources(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        rows = p.sources.order_by(KnowledgeSource.created_at.desc()).all()
        return jsonify([s.to_dict(with_content=False) for s in rows])

    @app.get("/api/projects/<int:pid>/sources/search")
    def search_sources(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404

        query = (request.args.get("q") or "").strip()
        limit = max(1, min(int(request.args.get("limit", Config.OPENALEX_PER_PAGE)), 10))
        if len(query) < 2:
            return jsonify({
                "query": query,
                "local": [],
                "external": [],
                "external_error": None,
            })

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
            .limit(limit)
            .all()
        )
        existing_rows = p.sources.all()

        sources = request.args.getlist("source") or None
        found = connectors.search_all(query, sources=sources, per_source_limit=limit)
        external = _mark_external_results(found["records"], existing_rows)
        external_error = None
        if not external and found["errors"]:
            external_error = "; ".join(f"{k}: {v}" for k, v in found["errors"].items())

        return jsonify({
            "query": query,
            "local": [s.to_dict(with_content=False) for s in local_rows],
            "external": external,
            "external_stats": found["stats"],
            "external_errors": found["errors"],
            "external_error": external_error,
        })

    @app.post("/api/projects/<int:pid>/sources")
    def add_source(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        d = request.get_json(force=True) or {}
        if not (d.get("title") and d.get("content")):
            return jsonify({"error": "Поля title и content обязательны"}), 400
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
        return jsonify(s.to_dict(with_content=False)), 201

    @app.post("/api/projects/<int:pid>/sources/import-openalex")
    def import_openalex_source(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404

        d = request.get_json(force=True) or {}
        title = (d.get("title") or "").strip()
        content = (d.get("content") or "").strip()
        if not (title and content):
            return jsonify({"error": "Для импорта нужны title и content"}), 400

        year = _parse_year(d.get("year"))
        reference = (d.get("reference") or "").strip() or (d.get("external_id") or "").strip() or None
        authors = (d.get("authors") or "").strip() or None

        existing_rows = p.sources.all()
        existing = _match_existing_source(
            {"title": title, "year": year, "reference": reference},
            *_source_lookups(existing_rows),
        )
        if existing:
            return jsonify({"created": False, "source": existing.to_dict(with_content=False)}), 200

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
        return jsonify({"created": True, "source": s.to_dict(with_content=False)}), 201

    @app.post("/api/projects/<int:pid>/knowledge/acquire")
    def acquire_knowledge(pid):
        """По теме найти внешние научные источники и импортировать в базу знаний.

        Тело: {topic?, sources?: [str], limit?, max_import?, preview?}
        preview=true — только показать найденное, без импорта.
        """
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        d = request.get_json(force=True) or {}
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
            return jsonify({"error": f"Ошибка поиска источников: {e}"}), 502
        return jsonify(result)

    @app.post("/api/projects/<int:pid>/weights/suggest")
    def weights_suggest(pid):
        """Модель предлагает веса ранжирования под проект (можно переопределить экспертом)."""
        try:
            return jsonify(suggest_weights(pid))
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:  # noqa
            return jsonify({"error": f"Не удалось предложить веса: {e}"}), 502

    @app.put("/api/sources/<int:sid>")
    def update_source(sid):
        s = db.session.get(KnowledgeSource, sid)
        if not s:
            return jsonify({"error": "Источник не найден"}), 404
        d = request.get_json(force=True) or {}
        for f in ("title", "content", "source_type", "authors", "year", "reference"):
            if f in d:
                setattr(s, f, _parse_year(d[f]) if f == "year" else d[f])
        db.session.commit()
        return jsonify(s.to_dict(with_content=False))

    @app.delete("/api/sources/<int:sid>")
    def delete_source(sid):
        s = db.session.get(KnowledgeSource, sid)
        if not s:
            return jsonify({"error": "Источник не найден"}), 404
        db.session.delete(s)
        db.session.commit()
        return jsonify({"deleted": sid})

    # ── Generation ──────────────────────────────────────────────────────────
    @app.post("/api/projects/<int:pid>/generate")
    def generate(pid):
        """Сгенерировать гипотезы через RAG+reranker.

        Тело: {n?, top_k?, weights?, weight_mode?: expert|model|default, topic?,
               use_rerank?, candidate_pool?, acquire_external?, sources?, max_import?}
        """
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404

        d = request.get_json(force=True) or {}
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
            return jsonify({"error": str(e)}), 404
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:  # noqa
            return jsonify({"error": f"Внутренняя ошибка генерации: {e}"}), 500

        resp = {"run": run, "hypotheses": hyps}
        if acquired is not None:
            resp["acquired"] = acquired
        return jsonify(resp), 201

    # ── Hypotheses ──────────────────────────────────────────────────────────
    @app.get("/api/projects/<int:pid>/hypotheses")
    def list_hypotheses(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        weights = _parse_weights(request.args.get("weights")) or DEFAULT_WEIGHTS
        status = request.args.get("status")
        q = p.hypotheses
        if status:
            q = q.filter(Hypothesis.status == status)
        rows = q.all()
        out = [h.to_dict(weights) for h in rows]
        out.sort(key=lambda x: x["composite"], reverse=True)
        return jsonify(out)

    @app.get("/api/projects/<int:pid>/hypotheses/export")
    def export_hypotheses(pid):
        """Экспорт ранжированных гипотез: format=md|json|csv."""
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        fmt = (request.args.get("format") or "md").lower()
        weights = _parse_weights(request.args.get("weights")) or DEFAULT_WEIGHTS
        hyps = [h.to_dict(weights) for h in p.hypotheses.all()]
        hyps.sort(key=lambda x: x["composite"], reverse=True)
        project = p.to_dict()

        if fmt == "json":
            return jsonify({"project": project, "weights": weights, "hypotheses": hyps})
        if fmt == "csv":
            return Response(
                export.to_csv(hyps),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=hypotheses_{pid}.csv"},
            )
        return Response(
            export.to_markdown(project, hyps, weights),
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=hypotheses_{pid}.md"},
        )

    @app.patch("/api/hypotheses/<int:hid>")
    def update_hypothesis(hid):
        """Экспертная корректировка: статус, заметки, переопределение оценок, правка текста."""
        h = db.session.get(Hypothesis, hid)
        if not h:
            return jsonify({"error": "Гипотеза не найдена"}), 404
        d = request.get_json(force=True) or {}
        if "status" in d and d["status"] in ("proposed", "accepted", "rejected", "review"):
            h.status = d["status"]
        if "expert_notes" in d:
            h.expert_notes = d["expert_notes"]
        if "expert_scores" in d:
            # частичное переопределение оценок экспертом (или сброс = null)
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
        weights = _parse_weights(d.get("weights")) or DEFAULT_WEIGHTS
        return jsonify(h.to_dict(weights))

    @app.delete("/api/hypotheses/<int:hid>")
    def delete_hypothesis(hid):
        h = db.session.get(Hypothesis, hid)
        if not h:
            return jsonify({"error": "Гипотеза не найдена"}), 404
        db.session.delete(h)
        db.session.commit()
        return jsonify({"deleted": hid})

    # ── Runs (аудит/прозрачность) ───────────────────────────────────────────
    @app.get("/api/projects/<int:pid>/runs")
    def list_runs(pid):
        p = db.session.get(Project, pid)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        rows = p.runs.order_by(GenerationRun.created_at.desc()).all()
        return jsonify([r.to_dict() for r in rows])

    @app.get("/api/runs/<int:rid>")
    def get_run(rid):
        r = db.session.get(GenerationRun, rid)
        if not r:
            return jsonify({"error": "Запуск не найден"}), 404
        return jsonify(r.to_dict())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
