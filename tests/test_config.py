from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings
from app.db.session import normalize_database_url


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_settings_reject_invalid_starting_bankroll(value: float) -> None:
    with pytest.raises(ValueError, match="STARTING_BANKROLL"):
        Settings(starting_bankroll=Decimal(str(value)))


def test_settings_read_environment_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "placeholder")
    monkeypatch.setenv("STARTING_BANKROLL", "250.5")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.odds_api_key == "placeholder"
    assert settings.starting_bankroll == 250.5
    assert settings.data_dir == tmp_path


def test_settings_require_database_url_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings.from_env()

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    with pytest.raises(ValueError, match="APP_API_KEY"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("configured", "normalized"),
    [
        ("postgres://user:secret@db.example/app", "postgresql+psycopg://user:secret@db.example/app"),
        ("postgresql://user:secret@db.example/app", "postgresql+psycopg://user:secret@db.example/app"),
        ("postgresql+psycopg://user:secret@db.example/app", "postgresql+psycopg://user:secret@db.example/app"),
    ],
)
def test_database_url_normalization_is_vendor_neutral(configured: str, normalized: str) -> None:
    assert normalize_database_url(configured) == normalized


def test_settings_reject_malformed_environment_bankroll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARTING_BANKROLL", "not-a-number")
    with pytest.raises(ValueError, match="STARTING_BANKROLL"):
        Settings.from_env()
