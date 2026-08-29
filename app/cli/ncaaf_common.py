from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.ncaaf_store import ImmutableArtifactStore
from app.db.session import create_database_engine, create_session_factory
from app.persistence.ncaaf_repository import NcaafRepository
from app.providers.cfbd import CfbdClient
from app.services.ncaaf_ingestion_service import NcaafIngestionService


def research_runtime() -> tuple[sessionmaker[Session], CfbdClient, ImmutableArtifactStore]:
    factory, store = research_index_runtime()
    api_key = os.getenv("CFBD_API_KEY")
    if not api_key:
        raise RuntimeError("CFBD_API_KEY is required; no network request was made")
    timeout = float(os.getenv("CFBD_TIMEOUT_SECONDS", "30"))
    return factory, CfbdClient(api_key, timeout_seconds=timeout), store


def research_index_runtime() -> tuple[sessionmaker[Session], ImmutableArtifactStore]:
    load_dotenv()
    database_url = (
        os.getenv("NCAAF_RESEARCH_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "sqlite+pysqlite:///.ncaaf-data/audit.sqlite"
    )
    store = ImmutableArtifactStore(Path(os.getenv("NCAAF_ARTIFACT_DIR", ".ncaaf-data")))
    factory = create_session_factory(create_database_engine(database_url))
    return factory, store


def service_for(
    session: Session,
    client: CfbdClient,
    store: ImmutableArtifactStore,
) -> NcaafIngestionService:
    return NcaafIngestionService(client, NcaafRepository(session), store)
