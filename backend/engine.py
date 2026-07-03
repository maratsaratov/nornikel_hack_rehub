"""Ядро «Фабрики гипотез»: генерация и ранжирование.

Пайплайн (полностью прозрачный, каждый шаг логируется в GenerationRun):
  1. TF-IDF отбирает релевантные источники под KPI  (retrieval.py)
  2. Промпт с пронумерованными источниками уходит в модель  (prompts.py, llm.py)
  3. Модель возвращает гипотезы с покомпонентными оценками и ссылками на источники
  4. Итоговый ранг считается прозрачной формулой composite_score (models.py)
"""
from db import db
from models import Project, KnowledgeSource, Hypothesis, GenerationRun, composite_score, DEFAULT_WEIGHTS
from retrieval import retrieve
from prompts import build_generation_prompt
from llm import complete_json


def _clamp(x, lo=0, hi=100):
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _build_retrieval_query(project: Project) -> str:
    return " ".join(filter(None, [
        project.kpi_target, project.kpi_metric, project.domain, project.constraints,
    ]))


def generate_hypotheses(project_id: int, n: int = 5, top_k: int = 6, weights: dict = None):
    """Сгенерировать n гипотез для проекта. Возвращает (run_dict, [hypothesis_dict])."""
    project = db.session.get(Project, project_id)
    if not project:
        raise ValueError("Проект не найден")

    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    sources = project.sources.all()

    # 1. Прозрачный отбор источников
    retrieved = retrieve(_build_retrieval_query(project), sources, top_k=top_k)
    retrieved_log = [{
        "source_id": item["source"].id,
        "title": item["source"].title,
        "type": item["source"].source_type,
        "score": item["score"],
        "terms": item["terms"],
    } for item in retrieved]

    # 2. Промпт
    system, user, id_map = build_generation_prompt(project, retrieved, n)

    run = GenerationRun(
        project_id=project.id,
        model=None,
        weights=weights,
        retrieved=retrieved_log,
        n_requested=n,
        prompt_preview=user[:6000],
    )
    db.session.add(run)
    db.session.flush()  # получить run.id

    # 3. Вызов модели
    try:
        data, usage = complete_json(system, user)
    except Exception as e:  # noqa
        run.error = f"Ошибка вызова модели: {e}"
        db.session.commit()
        raise RuntimeError(run.error)

    from config import Config
    run.model = Config.OPENAI_MODEL
    run.usage = usage

    raw_list = data.get("hypotheses") or data.get("data") or []
    if isinstance(raw_list, dict):
        raw_list = [raw_list]

    created = []
    for item in raw_list:
        scores = {
            "novelty": _clamp(item.get("novelty")),
            "value": _clamp(item.get("value")),
            "feasibility": _clamp(item.get("feasibility")),
            "risk": _clamp(item.get("risk")),
        }
        # Сопоставляем evidence-ссылки [S1] -> реальный source.id
        evidence = []
        for ev in (item.get("evidence") or []):
            sid = str(ev.get("source_id", "")).strip().upper().lstrip("[").rstrip("]")
            real_id = id_map.get(sid)
            src = next((r["source"] for r in retrieved if r["source"].id == real_id), None)
            evidence.append({
                "source_id": real_id,
                "title": src.title if src else ev.get("title"),
                "snippet": ev.get("snippet"),
                "relevance": ev.get("relevance"),
            })

        h = Hypothesis(
            project_id=project.id,
            run_id=run.id,
            statement=(item.get("statement") or "").strip(),
            rationale=item.get("rationale"),
            mechanism=item.get("mechanism"),
            validation=item.get("validation"),
            tags=item.get("tags") or [],
            novelty=scores["novelty"], novelty_rationale=item.get("novelty_rationale"),
            value=scores["value"], value_rationale=item.get("value_rationale"),
            feasibility=scores["feasibility"], feasibility_rationale=item.get("feasibility_rationale"),
            risk=scores["risk"], risk_rationale=item.get("risk_rationale"),
            evidence=evidence,
            status="proposed",
        )
        if h.statement:
            db.session.add(h)
            created.append(h)

    db.session.commit()

    # 4. Прозрачное ранжирование
    created.sort(key=lambda x: composite_score(x.effective_scores(), weights), reverse=True)
    return run.to_dict(), [h.to_dict(weights) for h in created]
