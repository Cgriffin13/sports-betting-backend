from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_phase5b1_upgrade_downgrade_and_schema_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "phase3-migrations.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert {
        "market_snapshots",
        "canonical_events",
        "provider_event_mappings",
        "sportsbooks",
        "provider_sportsbooks",
        "market_observations",
        "source_manifests",
        "canonical_programs",
        "canonical_venues",
        "football_game_facts",
        "model_registry_entries",
        "artifact_registry_entries",
        "shadow_predictions",
        "shadow_prediction_outcomes",
    } <= set(inspect(engine).get_table_names())
    engine.dispose()

    command.downgrade(config, "-1")
    engine = create_engine(database_url)
    tables_after_downgrade = set(inspect(engine).get_table_names())
    assert "portfolios" in tables_after_downgrade
    assert "market_snapshots" in tables_after_downgrade
    assert "source_manifests" in tables_after_downgrade
    assert "model_registry_entries" not in tables_after_downgrade
    assert "home_program_id" in {column["name"] for column in inspect(engine).get_columns("canonical_events")}
    engine.dispose()

    command.upgrade(config, "head")
    command.check(config)
