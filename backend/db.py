"""Единый экземпляр SQLAlchemy, чтобы избежать циклических импортов."""
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    inspect,
    or_,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, scoped_session, sessionmaker

engine = None
db_session = scoped_session(sessionmaker())


class Base(DeclarativeBase):
    pass


class _QueryProperty:
    def __get__(self, obj, cls):
        return db_session.query(cls)


class Model(Base):
    __abstract__ = True
    query = _QueryProperty()


class DB:
    Model = Model
    Column = Column
    Integer = Integer
    String = String
    Text = Text
    Float = Float
    DateTime = DateTime
    ForeignKey = ForeignKey
    JSON = JSON
    relationship = staticmethod(relationship)

    @property
    def session(self):
        return db_session

    @property
    def engine(self):
        return engine

    def init_app(self, database_url: str, engine_options: dict | None = None):
        global engine
        opts = dict(engine_options or {})
        if database_url.startswith("sqlite"):
            from sqlalchemy.pool import StaticPool
            opts.setdefault("connect_args", {"check_same_thread": False})
            if ":memory:" in database_url:
                opts["poolclass"] = StaticPool
                # StaticPool не принимает параметры размера пула
                for key in ("pool_size", "max_overflow", "pool_timeout"):
                    opts.pop(key, None)
        engine = create_engine(database_url, **opts)
        db_session.configure(bind=engine)

    def create_all(self):
        Base.metadata.create_all(bind=engine)


db = DB()

__all__ = ["db", "inspect", "or_", "text"]
