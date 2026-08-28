import json
from pathlib import Path

from app.persistence.json_repository import JsonPortfolioRepository
from app.persistence.memory_repository import InMemoryPortfolioRepository


def test_json_repository_round_trip_preserves_existing_shape(tmp_path: Path) -> None:
    repository = JsonPortfolioRepository(tmp_path, 200.0)
    portfolio = repository.get_or_create("main")
    portfolio["bankroll"] = 190.0
    portfolio["bets"].append({"bet_id": "one"})
    repository.save_portfolio("main", portfolio)

    reloaded = JsonPortfolioRepository(tmp_path, 200.0).get_or_create("main")
    assert reloaded == {"bankroll": 190.0, "bets": [{"bet_id": "one"}]}
    assert json.loads((tmp_path / "portfolio_db.json").read_text(encoding="utf-8"))["portfolios"]["main"] == reloaded


def test_json_repository_falls_back_from_invalid_file(tmp_path: Path) -> None:
    (tmp_path / "portfolio_db.json").write_text("not json", encoding="utf-8")
    repository = JsonPortfolioRepository(tmp_path, 325.0)
    assert repository.get_or_create("main") == {"bankroll": 325.0, "bets": []}


def test_repository_contract_auto_creates_portfolios() -> None:
    repository = InMemoryPortfolioRepository(275.0)
    assert repository.get_or_create("new") == {"bankroll": 275.0, "bets": []}
    assert repository.save_count == 1
