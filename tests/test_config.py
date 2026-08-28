from pathlib import Path

import pytest

from app.config import Settings


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_settings_reject_invalid_starting_bankroll(value: float) -> None:
    with pytest.raises(ValueError, match="STARTING_BANKROLL"):
        Settings(starting_bankroll=value)


def test_settings_read_environment_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "placeholder")
    monkeypatch.setenv("STARTING_BANKROLL", "250.5")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.odds_api_key == "placeholder"
    assert settings.starting_bankroll == 250.5
    assert settings.data_dir == tmp_path


def test_settings_reject_malformed_environment_bankroll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARTING_BANKROLL", "not-a-number")
    with pytest.raises(ValueError, match="STARTING_BANKROLL"):
        Settings.from_env()
