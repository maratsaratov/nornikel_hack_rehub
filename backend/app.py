"""Flask API «Фабрики гипотез»."""
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import inspect, or_, text

from config import Config
from db import db
from models import Project, KnowledgeSource, Hypothesis, GenerationRun, DEFAULT_WEIGHTS, composite_score
from engine import generate_hypotheses
import llm
from openalex import search_works


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


def _ensure_source_origin_column():
    inspector = inspect(db.engine)
    columns = {column["name"] for column in inspector.get_columns("knowledge_sources")}
    if "origin" in columns:
        return

    db.session.execute(text("ALTER TABLE knowledge_sources ADD COLUMN origin VARCHAR(40)"))
    db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_source_origin_column()
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

    @app.get("/api/config")
    def get_config():
        return jsonify({
            "model": Config.OPENAI_MODEL,
            "default_weights": DEFAULT_WEIGHTS,
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

        external = []
        external_error = None
        try:
            external = _mark_external_results(search_works(query, per_page=limit), existing_rows)
        except RuntimeError as exc:
            external_error = str(exc)

        return jsonify({
            "query": query,
            "local": [s.to_dict(with_content=False) for s in local_rows],
            "external": external,
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
        d = request.get_json(force=True) or {}
        n = int(d.get("n", 5))
        n = max(1, min(n, 10))
        top_k = int(d.get("top_k", 6))
        weights = _parse_weights(d.get("weights")) or DEFAULT_WEIGHTS
        try:
            run, hyps = generate_hypotheses(pid, n=n, top_k=top_k, weights=weights)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:  # noqa
            return jsonify({"error": f"Внутренняя ошибка генерации: {e}"}), 500
        return jsonify({"run": run, "hypotheses": hyps}), 201

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
