from decimal import Decimal
from pathlib import Path
from typing import Any

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


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_max_retries": -1},
        {"provider_max_retries": 6},
        {"provider_backoff_seconds": -0.1},
        {"provider_cache_ttl_seconds": -1},
        {"provider_low_quota_threshold": -1},
        {"market_freshness_seconds": 0},
        {"provider_quote_max_age_seconds": 120},
    ],
)
def test_settings_reject_invalid_provider_and_freshness_policy(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Settings(**overrides)


def test_settings_read_provider_and_freshness_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_TIMEOUT_SECONDS", "8.5")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "3")
    monkeypatch.setenv("PROVIDER_BACKOFF_SECONDS", "0.1")
    monkeypatch.setenv("PROVIDER_CACHE_TTL_SECONDS", "30")
    monkeypatch.setenv("PROVIDER_LOW_QUOTA_THRESHOLD", "7")
    monkeypatch.setenv("MARKET_FRESHNESS_SECONDS", "180")
    monkeypatch.setenv("PROVIDER_QUOTE_MAX_AGE_SECONDS", "86400")

    settings = Settings.from_env()

    assert settings.provider_timeout_seconds == 8.5
    assert settings.provider_max_retries == 3
    assert settings.provider_backoff_seconds == 0.1
    assert settings.provider_cache_ttl_seconds == 30
    assert settings.provider_low_quota_threshold == 7
    assert settings.market_freshness_seconds == 180
    assert settings.provider_quote_max_age_seconds == 86400


def test_settings_reject_malformed_environment_bankroll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARTING_BANKROLL", "not-a-number")
    with pytest.raises(ValueError, match="STARTING_BANKROLL"):
        Settings.from_env()


@pytest.mark.parametrize(
    "overrides",
    [
        {"pricing_minimum_books": 1},
        {"pricing_minimum_ev": Decimal("-0.01")},
        {"pricing_minimum_probability_edge": Decimal("-0.01")},
        {"pricing_outlier_threshold": Decimal("-0.01")},
        {"pricing_maximum_dispersion": Decimal("-0.01")},
        {"pricing_maximum_dispersion": Decimal("1.01")},
        {
            "pricing_outlier_threshold": Decimal("0.10"),
            "pricing_maximum_dispersion": Decimal("0.05"),
        },
        {"pricing_supported_books": ()},
    ],
)
def test_settings_reject_invalid_pricing_policy(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Pricing|PRICING"):
        Settings(**overrides)


def test_settings_read_pricing_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICING_MINIMUM_BOOKS", "3")
    monkeypatch.setenv("PRICING_MINIMUM_EV", "0.02")
    monkeypatch.setenv("PRICING_MINIMUM_PROBABILITY_EDGE", "0.01")
    monkeypatch.setenv("PRICING_OUTLIER_THRESHOLD", "0.04")
    monkeypatch.setenv("PRICING_MAXIMUM_DISPERSION", "0.09")
    monkeypatch.setenv("PRICING_SUPPORTED_BOOKS", "draftkings, fanduel")

    settings = Settings.from_env()

    assert settings.pricing_minimum_books == 3
    assert settings.pricing_minimum_ev == Decimal("0.02")
    assert settings.pricing_minimum_probability_edge == Decimal("0.01")
    assert settings.pricing_outlier_threshold == Decimal("0.04")
    assert settings.pricing_maximum_dispersion == Decimal("0.09")
    assert settings.pricing_supported_books == ("draftkings", "fanduel")


def test_settings_reject_malformed_environment_pricing_decimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICING_MINIMUM_EV", "not-a-number")
    with pytest.raises(ValueError, match="PRICING_MINIMUM_EV"):
        Settings.from_env()
