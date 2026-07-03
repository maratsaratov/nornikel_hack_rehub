"""Flask API «Фабрики гипотез»."""
import json
from flask import Flask, request, jsonify
from flask_cors import CORS

from config import Config
from db import db
from models import Project, KnowledgeSource, Hypothesis, GenerationRun, DEFAULT_WEIGHTS, composite_score
from engine import generate_hypotheses
import llm


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


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app)
    db.init_app(app)

    with app.app_context():
        db.create_all()
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
        return jsonify([s.to_dict() for s in rows])

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
            authors=d.get("authors"),
            year=d.get("year"),
            reference=d.get("reference"),
        )
        db.session.add(s)
        db.session.commit()
        return jsonify(s.to_dict()), 201

    @app.put("/api/sources/<int:sid>")
    def update_source(sid):
        s = db.session.get(KnowledgeSource, sid)
        if not s:
            return jsonify({"error": "Источник не найден"}), 404
        d = request.get_json(force=True) or {}
        for f in ("title", "content", "source_type", "authors", "year", "reference"):
            if f in d:
                setattr(s, f, d[f])
        db.session.commit()
        return jsonify(s.to_dict())

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
