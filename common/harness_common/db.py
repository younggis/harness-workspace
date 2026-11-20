"""SQLAlchemy engine/session helpers and schema targeting."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings


def make_engine(url: str, *, schema: str | None = None, echo: bool = False) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        return engine
    engine = create_engine(url, **kwargs)
    if schema:
        # Map our tables onto the dedicated schema without rewriting model __table_args__.
        from . import models  # noqa: F401

        @event.listens_for(engine, "connect")
        def _set_search_path(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            try:
                cur.execute(f'SET search_path TO "{schema}", pg_catalog')
                # A leaked session holding an idle transaction can block DDL
                # (migrations, rebuild bookkeeping) indefinitely. Bound it.
                cur.execute("SET statement_timeout = '120s'")
                cur.execute("SET idle_in_transaction_session_timeout = '60s'")
                dbapi_conn.commit()
            finally:
                cur.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def session_scope(factory: sessionmaker) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        if session.in_transaction():
            session.rollback()
        session.close()


def ping(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
