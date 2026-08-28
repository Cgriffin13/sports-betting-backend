from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def normalize_database_url(database_url: str) -> str:
    """Select psycopg for generic PostgreSQL URLs without vendor-specific behavior."""
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url.removeprefix("postgres://")
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def create_database_engine(database_url: str) -> Engine:
    normalized = normalize_database_url(database_url)
    connect_args = {"check_same_thread": False} if normalized.startswith("sqlite") else {}
    return create_engine(normalized, pool_pre_ping=True, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
