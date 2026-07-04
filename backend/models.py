"""Модели данных «Фабрики гипотез».

Схема отражает прозрачный пайплайн:
  Project (KPI)  ->  KnowledgeSource (база знаний)
        |                     |
        +----> GenerationRun (аудит: веса, отобранные источники, модель)
                     |
                     +----> Hypothesis (гипотеза + покомпонентные оценки + evidence)
"""
from datetime import datetime

from sqlalchemy import UniqueConstraint

from db import db


# Веса ранжирования по умолчанию. Итоговый скор — прозрачная взвешенная сумма,
# а НЕ «оценка от чёрного ящика». Эксперт меняет веса на лету.
DEFAULT_WEIGHTS = {
    "novelty": 0.25,      # новизна
    "value": 0.30,        # потенциальная ценность
    "feasibility": 0.25,  # реализуемость / проверяемость
    "risk": 0.20,         # риск (входит инвертированно: 100 - risk)
}

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(160))
    password_hash = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    memberships = db.relationship("ProjectMembership", back_populates="user",
                                  cascade="all, delete-orphan", lazy="dynamic")
    created_projects = db.relationship("Project", back_populates="created_by",
                                       foreign_keys="Project.created_by_id", lazy="dynamic")
    sessions = db.relationship("AuthSession", back_populates="user",
                               cascade="all, delete-orphan", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
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
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
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
    documents = db.relationship("SourceDocument", backref="project",
                                 cascade="all, delete-orphan", lazy="dynamic")
    metrics = db.relationship("ProjectMetric", back_populates="project",
                              cascade="all, delete-orphan", lazy="dynamic")
    memberships = db.relationship("ProjectMembership", back_populates="project",
                                  cascade="all, delete-orphan", lazy="dynamic")
    created_by = db.relationship("User", back_populates="created_projects",
                                 foreign_keys=[created_by_id])

    def to_dict(self, current_user_role=None):
        return {
            "id": self.id,
            "created_by_id": self.created_by_id,
            "title": self.title,
            "kpi_target": self.kpi_target,
            "kpi_metric": self.kpi_metric,
            "metrics": [m.to_dict() for m in self.metrics.order_by(ProjectMetric.position.asc(), ProjectMetric.id.asc()).all()],
            "kpi_direction": self.kpi_direction,
            "domain": self.domain,
            "constraints": self.constraints,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source_count": self.sources.count(),
            "hypothesis_count": self.hypotheses.count(),
            "member_count": self.memberships.count(),
            "current_user_role": current_user_role,
            "can_manage_project": current_user_role == ROLE_OWNER,
            "can_manage_members": current_user_role == ROLE_OWNER,
        }


class ProjectMetric(db.Model):
    __tablename__ = "project_metrics"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    name = db.Column(db.String(300), nullable=False)
    unit = db.Column(db.String(120))
    current_value = db.Column(db.String(120))
    target_value = db.Column(db.String(120))
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", back_populates="metrics")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "unit": self.unit or "",
            "current": self.current_value or "",
            "target": self.target_value or "",
            "position": self.position or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ProjectMembership(db.Model):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_membership"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default=ROLE_MEMBER)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", back_populates="memberships")
    user = db.relationship("User", back_populates="memberships")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "role": self.role,
            "user": self.user.to_dict() if self.user else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuthSession(db.Model):
    __tablename__ = "auth_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="sessions")


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
            "is_external": (self.origin or "manual") != "manual",
            "authors": self.authors,
            "year": self.year,
            "reference": self.reference,
            "excerpt": excerpt,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if with_content:
            d["content"] = self.content
        return d

    @property
    def retrieval_kind(self) -> str:
        return "source"

    @property
    def retrieval_id(self) -> str:
        return f"source:{self.id}"


class SourceDocument(db.Model):
    """Uploaded source file parsed by the deterministic ingestion subsystem."""
    __tablename__ = "source_documents"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    stored_path = db.Column(db.String(1000), nullable=False)
    file_type = db.Column(db.String(40), nullable=False)
    parse_status = db.Column(db.String(40), default="uploaded")
    metadata_json = db.Column(db.JSON)
    raw_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chunks = db.relationship("DocumentChunk", backref="document",
                             cascade="all, delete-orphan", lazy="dynamic")
    tables = db.relationship("DocumentTable", backref="document",
                             cascade="all, delete-orphan", lazy="dynamic")
    parse_runs = db.relationship("DocumentParseRun", backref="document",
                                 cascade="all, delete-orphan", lazy="dynamic")

    def to_dict(self, with_raw_text=False):
        raw = self.raw_text or ""
        preview = " ".join(raw.split())
        if len(preview) > 500:
            preview = preview[:497].rstrip() + "..."
        metadata = self.metadata_json or {}
        summary = metadata.get("summary") or metadata.get("description")
        data = {
            "id": self.id,
            "project_id": self.project_id,
            "filename": self.filename,
            "stored_path": self.stored_path,
            "file_type": self.file_type,
            "parse_status": self.parse_status,
            "metadata": metadata,
            "summary": summary,
            "description": summary,
            "raw_text_preview": preview,
            "chunk_count": self.chunks.count() if self.id else 0,
            "table_count": self.tables.count() if self.id else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_raw_text:
            data["raw_text"] = raw
        return data

    @property
    def title(self) -> str:
        metadata = self.metadata_json or {}
        return str(metadata.get("title") or self.filename or "").strip()

    @property
    def content(self) -> str:
        metadata = self.metadata_json or {}
        return str(self.raw_text or metadata.get("summary") or metadata.get("description") or "").strip()

    @property
    def source_type(self) -> str:
        metadata = self.metadata_json or {}
        if metadata.get("source_type"):
            return str(metadata["source_type"])
        if self.file_type in {"xlsx", "csv"}:
            return "dataset"
        return "uploaded_document"

    @property
    def origin(self) -> str:
        return "upload"

    @property
    def authors(self) -> str | None:
        metadata = self.metadata_json or {}
        value = metadata.get("authors")
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return ", ".join(cleaned) if cleaned else None
        text = str(value or "").strip()
        return text or None

    @property
    def year(self) -> int | None:
        metadata = self.metadata_json or {}
        value = metadata.get("year")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def retrieval_kind(self) -> str:
        return "document"

    @property
    def retrieval_id(self) -> str:
        return f"document:{self.id}"


class DocumentChunk(db.Model):
    __tablename__ = "document_chunks"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("source_documents.id"), nullable=False)
    chunk_index = db.Column(db.Integer, nullable=False)
    section_title = db.Column(db.String(500))
    page_ref = db.Column(db.String(120))
    text = db.Column(db.Text, nullable=False)
    meta_json = db.Column(db.JSON)

    def to_dict(self):
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "section_title": self.section_title,
            "page_ref": self.page_ref,
            "text": self.text,
            "meta": self.meta_json or {},
        }


class DocumentTable(db.Model):
    __tablename__ = "document_tables"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("source_documents.id"), nullable=False)
    table_name = db.Column(db.String(300))
    sheet_name = db.Column(db.String(300))
    table_json = db.Column(db.JSON)

    def to_dict(self):
        payload = self.table_json or {}
        return {
            "id": self.id,
            "document_id": self.document_id,
            "table_name": self.table_name,
            "sheet_name": self.sheet_name,
            "table": payload,
        }


class DocumentParseRun(db.Model):
    __tablename__ = "document_parse_runs"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("source_documents.id"), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    warnings_json = db.Column(db.JSON)
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "document_id": self.document_id,
            "status": self.status,
            "warnings": self.warnings_json or [],
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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
