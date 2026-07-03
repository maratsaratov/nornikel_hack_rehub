"""Ядро «Фабрики гипотез»: генерация и ранжирование.

Пайплайн (прозрачный, каждый этап логируется в GenerationRun):
  1. RAG: chunking → TF-IDF отбор кандидатов → реранкер (rag.py)
  2. Веса ранжирования: заданы экспертом ИЛИ предложены моделью (suggest_weights)
  3. Промпт с пронумерованными источниками уходит в DeepSeek (prompts.py, llm.py)
  4. Модель возвращает гипотезы с покомпонентными оценками и ссылками на источники
  5. Итоговый ранг — прозрачная формула composite_score (models.py)
"""
from db import db
from models import Project, Hypothesis, GenerationRun, composite_score, DEFAULT_WEIGHTS
import rag
from prompts import build_generation_prompt, build_weight_prompt
from llm import complete_json
from config import Config

_AXES = ("novelty", "value", "feasibility", "risk")


def _clamp(x, lo=0, hi=100):
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_weights(w) -> dict:
    w = {k: max(0.0, float((w or {}).get(k, 0) or 0)) for k in _AXES}
    s = sum(w.values())
    if s <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: round(v / s, 3) for k, v in w.items()}


def _build_query(project: Project, topic: str = None) -> str:
    if (topic or "").strip():
        # тема — главный фокус, цель добавляем как контекст
        return " ".join(filter(None, [topic, project.kpi_target, project.kpi_metric, project.domain]))
    return " ".join(filter(None, [
        project.kpi_target, project.kpi_metric, project.domain, project.constraints,
    ]))


def suggest_weights(project_id: int) -> dict:
    """Модель предлагает веса ранжирования под конкретный проект/стадию."""
    project = db.session.get(Project, project_id)
    if not project:
        raise ValueError("Проект не найден")
    system, user = build_weight_prompt(project)
    data, usage = complete_json(system, user, max_tokens=1800)
    return {
        "weights": _normalize_weights(data.get("weights")),
        "rationale": data.get("rationale"),
        "notes": data.get("notes") or {},
        "usage": usage,
        "mode": "model",
    }


def generate_hypotheses(project_id: int, n: int = 5, top_k: int = 6, weights: dict = None,
                        weight_mode: str = "expert", topic: str = None,
                        use_rerank: bool = True, candidate_pool: int = None):
    """Сгенерировать n гипотез. Возвращает (run_dict, [hypothesis_dict])."""
    project = db.session.get(Project, project_id)
    if not project:
        raise ValueError("Проект не найден")

    # ── Веса: модель / эксперт / по умолчанию ────────────────────────────────
    weight_rationale = None
    if weight_mode == "model":
        sug = suggest_weights(project_id)
        weights, weight_rationale = sug["weights"], sug["rationale"]
    elif weights:
        weight_mode = "expert"
    else:
        weights, weight_mode = dict(DEFAULT_WEIGHTS), "default"
    weights = _normalize_weights(weights)

    sources = project.sources.all()
    query = _build_query(project, topic)

    # ── 1. RAG: TF-IDF → реранкер ────────────────────────────────────────────
    rag_out = rag.retrieve(query, sources, top_k=top_k, candidates=candidate_pool, use_rerank=use_rerank)
    items = rag_out["items"]
    src_by_id = {it["source"].id: it["source"] for it in items}
    retrieved_log = [{
        "source_id": it["source"].id,
        "title": it["source"].title,
        "type": it["source"].source_type,
        "origin": getattr(it["source"], "origin", None),
        "tfidf_score": it["tfidf_score"],
        "rerank_score": it["rerank_score"],
        "score": it["score"],
        "terms": it["terms"],
    } for it in items]

    # ── 2. Промпт ────────────────────────────────────────────────────────────
    system, user, id_map = build_generation_prompt(project, items, n, topic=topic)

    run = GenerationRun(
        project_id=project.id, model=None, weights=weights,
        weight_mode=weight_mode, weight_rationale=weight_rationale, topic=(topic or None),
        retrieved=retrieved_log, stages=rag_out["stages"], rerank_usage=rag_out["rerank_usage"],
        n_requested=n, prompt_preview=user[:6000],
    )
    db.session.add(run)
    db.session.flush()

    # ── 3. Генерация ─────────────────────────────────────────────────────────
    try:
        data, usage = complete_json(system, user)
    except Exception as e:  # noqa
        run.error = f"Ошибка вызова модели: {e}"
        db.session.commit()
        raise RuntimeError(run.error)

    run.model = Config.OPENAI_MODEL
    run.usage = usage

    raw_list = data.get("hypotheses") or data.get("data") or []
    if isinstance(raw_list, dict):
        raw_list = [raw_list]

    created = []
    for item in raw_list:
        scores = {k: _clamp(item.get(k)) for k in _AXES}
        evidence = []
        for ev in (item.get("evidence") or []):
            sid = str(ev.get("source_id", "")).strip().upper().lstrip("[").rstrip("]")
            real_id = id_map.get(sid)
            src = src_by_id.get(real_id)
            evidence.append({
                "source_id": real_id,
                "title": src.title if src else ev.get("title"),
                "snippet": ev.get("snippet"),
                "relevance": ev.get("relevance"),
            })

        h = Hypothesis(
            project_id=project.id, run_id=run.id,
            statement=(item.get("statement") or "").strip(),
            goal_link=item.get("goal_link"),
            rationale=item.get("rationale"),
            mechanism=item.get("mechanism"),
            validation=item.get("validation"),
            tags=item.get("tags") or [],
            novelty=scores["novelty"], novelty_rationale=item.get("novelty_rationale"),
            value=scores["value"], value_rationale=item.get("value_rationale"),
            feasibility=scores["feasibility"], feasibility_rationale=item.get("feasibility_rationale"),
            risk=scores["risk"], risk_rationale=item.get("risk_rationale"),
            evidence=evidence, status="proposed",
        )
        if h.statement:
            db.session.add(h)
            created.append(h)

    db.session.commit()

    # ── 4. Прозрачное ранжирование ───────────────────────────────────────────
    created.sort(key=lambda x: composite_score(x.effective_scores(), weights), reverse=True)
    return run.to_dict(), [h.to_dict(weights) for h in created]
