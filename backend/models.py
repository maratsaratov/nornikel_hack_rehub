"""Модели данных «Фабрики гипотез».

Схема отражает прозрачный пайплайн:
  Project (KPI)  ->  KnowledgeSource (база знаний)
        |                     |
        +----> GenerationRun (аудит: веса, отобранные источники, модель)
                     |
                     +----> Hypothesis (гипотеза + покомпонентные оценки + evidence)
"""
from datetime import datetime
from db import db


# Веса ранжирования по умолчанию. Итоговый скор — прозрачная взвешенная сумма,
# а НЕ «оценка от чёрного ящика». Эксперт меняет веса на лету.
DEFAULT_WEIGHTS = {
    "novelty": 0.25,      # новизна
    "value": 0.30,        # потенциальная ценность
    "feasibility": 0.25,  # реализуемость / проверяемость
    "risk": 0.20,         # риск (входит инвертированно: 100 - risk)
}


def composite_score(scores: dict, weights: dict = None) -> float:
    """Прозрачная формула итогового ранга.

    composite = Σ(w_i * s_i) / Σ(w_i),  где вклад риска = (100 - risk).
    Возвращает число 0..100. Никакой магии — чистая арифметика,
    которую эксперт может воспроизвести вручную.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    n = float(scores.get("novelty", 0) or 0)
    v = float(scores.get("value", 0) or 0)
    f = float(scores.get("feasibility", 0) or 0)
    r = float(scores.get("risk", 0) or 0)
    num = w["novelty"] * n + w["value"] * v + w["feasibility"] * f + w["risk"] * (100 - r)
    den = w["novelty"] + w["value"] + w["feasibility"] + w["risk"]
    return round(num / den, 1) if den else 0.0


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    kpi_target = db.Column(db.Text, nullable=False)          # текст цели
    kpi_metric = db.Column(db.String(200))                   # измеримая метрика
    kpi_direction = db.Column(db.String(20), default="increase")  # increase | decrease
    domain = db.Column(db.String(300))                       # область (сплавы, катализ, ...)
    constraints = db.Column(db.Text)                         # ограничения (бюджет, оборудование)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sources = db.relationship("KnowledgeSource", backref="project",
                              cascade="all, delete-orphan", lazy="dynamic")
    hypotheses = db.relationship("Hypothesis", backref="project",
                                 cascade="all, delete-orphan", lazy="dynamic")
    runs = db.relationship("GenerationRun", backref="project",
                           cascade="all, delete-orphan", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "kpi_target": self.kpi_target,
            "kpi_metric": self.kpi_metric,
            "kpi_direction": self.kpi_direction,
            "domain": self.domain,
            "constraints": self.constraints,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source_count": self.sources.count(),
            "hypothesis_count": self.hypotheses.count(),
        }


class KnowledgeSource(db.Model):
    __tablename__ = "knowledge_sources"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    title = db.Column(db.String(400), nullable=False)
    source_type = db.Column(db.String(40), default="literature")  # literature|report|experiment
    origin = db.Column(db.String(40), default="manual")  # manual|openalex
    content = db.Column(db.Text, nullable=False)
    authors = db.Column(db.String(400))
    year = db.Column(db.Integer)
    reference = db.Column(db.String(400))   # DOI / ссылка / инв. номер отчёта
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, with_content=True):
        excerpt = " ".join((self.content or "").split())
        if len(excerpt) > 240:
            excerpt = excerpt[:237].rstrip() + "..."
        d = {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "source_type": self.source_type,
            "origin": self.origin or "manual",
            "authors": self.authors,
            "year": self.year,
            "reference": self.reference,
            "excerpt": excerpt,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if with_content:
            d["content"] = self.content
        return d


class GenerationRun(db.Model):
    """Аудит одной генерации: что подали модели и с какими весами ранжировали."""
    __tablename__ = "generation_runs"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    model = db.Column(db.String(120))
    weights = db.Column(db.JSON)             # веса, применённые на момент генерации
    weight_mode = db.Column(db.String(20))   # expert | model | default
    weight_rationale = db.Column(db.Text)    # обоснование весов (если предложены моделью)
    topic = db.Column(db.String(400))        # свободная тема запроса (если задана)
    retrieved = db.Column(db.JSON)           # финальный контекст: [{source_id, title, bm25, dense, hybrid, rerank, terms, lang}]
    stages = db.Column(db.JSON)              # этапы RAG: {passages, candidates, reranked, rerank_model}
    rerank_usage = db.Column(db.JSON)        # стоимость реранкера
    n_requested = db.Column(db.Integer)
    prompt_preview = db.Column(db.Text)      # что реально ушло в модель (прозрачность)
    usage = db.Column(db.JSON)               # токены / стоимость
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hypotheses = db.relationship("Hypothesis", backref="run", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "model": self.model,
            "weights": self.weights,
            "weight_mode": self.weight_mode,
            "weight_rationale": self.weight_rationale,
            "topic": self.topic,
            "retrieved": self.retrieved,
            "stages": self.stages,
            "rerank_usage": self.rerank_usage,
            "n_requested": self.n_requested,
            "prompt_preview": self.prompt_preview,
            "usage": self.usage,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Hypothesis(db.Model):
    __tablename__ = "hypotheses"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    run_id = db.Column(db.Integer, db.ForeignKey("generation_runs.id"))

    statement = db.Column(db.Text, nullable=False)   # формулировка гипотезы
    goal_link = db.Column(db.Text)                   # связь с целью проекта (KPI)
    rationale = db.Column(db.Text)                   # научное обоснование
    mechanism = db.Column(db.Text)                   # предполагаемый механизм
    validation = db.Column(db.Text)                  # как проверить (эксперимент)
    tags = db.Column(db.JSON)                         # ключевые слова

    # Покомпонентные оценки (0..100) + обоснование каждой (интерпретируемость)
    novelty = db.Column(db.Float, default=0)
    novelty_rationale = db.Column(db.Text)
    value = db.Column(db.Float, default=0)
    value_rationale = db.Column(db.Text)
    feasibility = db.Column(db.Float, default=0)
    feasibility_rationale = db.Column(db.Text)
    risk = db.Column(db.Float, default=0)
    risk_rationale = db.Column(db.Text)

    evidence = db.Column(db.JSON)   # [{source_id, title, snippet, relevance}]

    # Экспертная корректировка
    status = db.Column(db.String(20), default="proposed")  # proposed|accepted|rejected|review
    expert_notes = db.Column(db.Text)
    expert_scores = db.Column(db.JSON)   # ручные переопределения оценок, если заданы

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def effective_scores(self):
        """Оценки с учётом экспертных правок (если эксперт что-то переопределил)."""
        base = {
            "novelty": self.novelty,
            "value": self.value,
            "feasibility": self.feasibility,
            "risk": self.risk,
        }
        if self.expert_scores:
            base.update({k: v for k, v in self.expert_scores.items() if v is not None})
        return base

    def to_dict(self, weights=None):
        eff = self.effective_scores()
        return {
            "id": self.id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "statement": self.statement,
            "goal_link": self.goal_link,
            "rationale": self.rationale,
            "mechanism": self.mechanism,
            "validation": self.validation,
            "tags": self.tags or [],
            "scores": {
                "novelty": self.novelty,
                "value": self.value,
                "feasibility": self.feasibility,
                "risk": self.risk,
            },
            "rationales": {
                "novelty": self.novelty_rationale,
                "value": self.value_rationale,
                "feasibility": self.feasibility_rationale,
                "risk": self.risk_rationale,
            },
            "evidence": self.evidence or [],
            "status": self.status,
            "expert_notes": self.expert_notes,
            "expert_scores": self.expert_scores,
            "effective_scores": eff,
            "composite": composite_score(eff, weights),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
