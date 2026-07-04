"""Шаблоны промптов: генерация гипотез и предложение весов ранжирования.

Интерпретируемость: модель обязана
  1) ссылаться на источники по ID ([S1], [S2] ...) — контекст отобран RAG+реранкером;
  2) выставлять оценки по 4 названным осям и обосновывать КАЖДУЮ;
  3) явно указывать связь гипотезы с целью проекта (goal_link).
Итоговый ранг считается вне модели прозрачной формулой (models.composite_score).
"""

SYSTEM_PROMPT = (
    "Ты — старший научный стратег НИОКР в области материаловедения, металлургии, "
    "катализа и электрохимии. Ты помогаешь исследовательским группам формулировать "
    "проверяемые научные гипотезы для достижения заданной цели/KPI. "
    "Контекст отобран RAG-пайплайном и переранжирован кросс-энкодером — опирайся на него. "
    "Ты рассуждаешь строго, не выдумываешь ссылки и не преувеличиваешь новизну."
)

_SCORE_GUIDE = """
Шкалы оценок (целые 0..100):
  novelty     — насколько идея нетривиальна относительно базы знаний (100 = прорыв);
  value       — ожидаемый вклад/эффект для цели (100 = решающий);
  feasibility — реализуемость проверки имеющимися ресурсами (100 = легко проверить);
  risk        — суммарный научно-технический риск/неопределённость (100 = очень высокий).
"""


def _format_context(items):
    """items: list rag-пассажей {source, passage, bm25_score, dense_score, hybrid_score, rerank_score, terms}."""
    lines, id_map = [], {}
    for i, item in enumerate(items, start=1):
        s = item["source"]
        sid = f"S{i}"
        id_map[sid] = s.id
        origin = getattr(s, "origin", None)
        meta = " · ".join(filter(None, [
            {"literature": "литература", "report": "отчёт", "experiment": "эксперимент",
             "dataset": "набор данных"}.get(s.source_type, s.source_type),
            str(s.year) if s.year else None,
            s.authors or None,
            f"источник: {origin}" if origin and origin != "manual" else None,
        ]))
        rr = item.get("rerank_score")
        if isinstance(rr, (int, float)):
            score_str = f"реранк={rr:.3f}"
        elif item.get("hybrid_score") is not None:
            score_str = f"гибрид={item.get('hybrid_score')}"
        else:
            score_str = f"bm25={item.get('bm25_score')}"
        terms = ", ".join(item.get("terms") or [])
        lines.append(
            f"[{sid}] {s.title} ({meta})\n"
            f"    {score_str}; совпавшие термины: {terms}\n"
            f"    {item.get('passage') or (s.content or '')[:900]}"
        )
    block = "\n\n".join(lines) if lines else (
        "(база знаний пуста — опирайся на общие принципы, но снижай feasibility и повышай risk)")
    return block, id_map


def build_generation_prompt(project, items, n: int, topic: str = None):
    """project: Project; items: rag-пассажи; n: сколько гипотез; topic: свободная тема (опц.)."""
    direction = "увеличить" if (project.kpi_direction or "increase") == "increase" else "снизить"
    kb_block, id_map = _format_context(items)
    focus = f"\nТЕМА/ФОКУС ЗАПРОСА: {topic}\n" if (topic or "").strip() else ""

    user = f"""ЦЕЛЬ И КОНТЕКСТ ПРОЕКТА
Проект: {project.title}
Цель (KPI): {project.kpi_target}
Метрика: {project.kpi_metric or "не задана"} (направление: {direction})
Область: {project.domain or "материаловедение"}
Ограничения/ресурсы: {project.constraints or "не заданы"}
{focus}
БАЗА ЗНАНИЙ (RAG: TF-IDF отбор → переранжирование кросс-энкодером)
{kb_block}

ЗАДАЧА
Сгенерируй {n} РАЗНООБРАЗНЫХ, взаимодополняющих и проверяемых научных гипотез для достижения цели.
Требования:
  • опирайся на конкретные источники и ссылайся на них по ID ([S1], [S2] ...);
  • каждая гипотеза — иной механизм/подход (не переформулировки одной идеи);
  • обязательно заполни goal_link — прямую связь с целью/метрикой проекта;
  • формулировка должна быть проверяемой в эксперименте;
  • оценки калибруй честно и обосновывай каждую;
  • если источников недостаточно — снижай feasibility и повышай risk.
{_SCORE_GUIDE}
"""
    return SYSTEM_PROMPT, user, id_map


# ── Предложение весов ранжирования моделью ───────────────────────────────────
WEIGHT_SYSTEM = (
    "Ты — методолог НИОКР. По описанию проекта и его стадии ты определяешь, как расставить "
    "веса важности критериев ранжирования гипотез (новизна, ценность/эффект, реализуемость, риск)."
)

_WEIGHT_GUIDE = """
Сумма весов должна быть близка к 1. Веса отражают приоритеты ПРОЕКТА:
  • ранняя/поисковая стадия, амбициозная цель  → выше novelty и value;
  • жёсткие ограничения по ресурсам/срокам/производству → выше feasibility и risk;
  • инкрементальное улучшение зрелой технологии → выше feasibility, ниже novelty.
"""


def build_weight_prompt(project):
    direction = "увеличить" if (project.kpi_direction or "increase") == "increase" else "снизить"
    user = f"""ПРОЕКТ
Название: {project.title}
Цель (KPI): {project.kpi_target}
Метрика: {project.kpi_metric or "не задана"} (направление: {direction})
Область: {project.domain or "материаловедение"}
Ограничения/ресурсы: {project.constraints or "не заданы"}

ЗАДАЧА
Предложи веса важности критериев ранжирования гипотез под ЭТОТ проект и его стадию.
{_WEIGHT_GUIDE}
"""
    return WEIGHT_SYSTEM, user
