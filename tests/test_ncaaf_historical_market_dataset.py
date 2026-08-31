from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.providers.odds_api_historical import HistoricalOddsResponse
from app.research.ncaaf.historical_market_dataset import (
    DATASET_VERSION,
    HistoricalMarketCache,
    LATER_NEW_CALL_LIMIT,
    MarketGame,
    MarketRequest,
    acquisition_plan_summary,
    build_historical_market_dataset,
    build_later_plan,
    build_morning_plan,
    execute_plan,
    load_market_games,
    select_later_robustness_games,
    validate_cached_plan,
    validate_historical_market_dataset,
)
from app.research.ncaaf.historical_odds_audit import CachedResponse


def _game(
    game_id: int,
    *,
    season: int = 2024,
    week: int = 1,
    season_type: str = "regular",
    kickoff: datetime | None = None,
) -> MarketGame:
    return MarketGame(
        provider_game_id=game_id,
        canonical_event_id=f"event-{game_id}",
        season=season,
        week=week,
        season_type=season_type,
        kickoff=kickoff or datetime(season, 9, 7, 16, tzinfo=UTC),
        home_program_id=f"program-home-{game_id}",
        away_program_id=f"program-away-{game_id}",
        home_team=f"Home {game_id}",
        away_team=f"Away {game_id}",
        home_classification="fbs",
        away_classification="fbs",
        model_eligible=True,
    )


def _book(key: str, game: MarketGame) -> dict[str, Any]:
    return {
        "key": key,
        "title": key.title(),
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": game.home_team, "price": -110},
                    {"name": game.away_team, "price": 100},
                ],
            },
            {
                "key": "spreads",
                "outcomes": [
                    {"name": game.home_team, "price": -110, "point": -3.5},
                    {"name": game.away_team, "price": -110, "point": 3.5},
                ],
            },
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": -105, "point": 52.5},
                    {"name": "Under", "price": -115, "point": 52.5},
                ],
            },
        ],
    }


def _payload(game: MarketGame, requested_at: datetime, *, books: int = 3) -> dict[str, Any]:
    return {
        "timestamp": requested_at.isoformat().replace("+00:00", "Z"),
        "data": [
            {
                "id": f"odds-{game.provider_game_id}",
                "commence_time": game.kickoff.isoformat().replace("+00:00", "Z"),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "bookmakers": [
                    _book(key, game)
                    for key in ("draftkings", "fanduel", "betmgm")[:books]
                ],
            }
        ],
    }


def _cached(request: MarketRequest, payload: dict[str, Any]) -> CachedResponse:
    return CachedResponse(
        request_hash=request.request_hash,
        content_hash="a" * 64,
        retrieved_at=datetime(2026, 8, 30, tzinfo=UTC),
        payload=payload,
        manifest={"request_parameters": request.safe_parameters},
        cache_hit=True,
    )


class _Cache:
    def __init__(self, values: dict[str, CachedResponse] | None = None) -> None:
        self.values = values or {}

    def find(self, request: MarketRequest) -> CachedResponse | None:
        return self.values.get(request.request_hash)

    def put(self, request: MarketRequest, response: HistoricalOddsResponse) -> CachedResponse:
        value = _cached(request, response.payload)
        self.values[request.request_hash] = value
        return value


def test_morning_plan_uses_first_scheduled_kickoff_minus_three_hours() -> None:
    first = _game(1, kickoff=datetime(2024, 9, 7, 16, tzinfo=UTC))
    second = _game(2, kickoff=datetime(2024, 9, 7, 23, tzinfo=UTC))

    plan = build_morning_plan((second, first))

    assert len(plan) == 1
    assert plan[0].requested_at == first.kickoff - timedelta(hours=3)
    assert plan[0].markets == ("h2h", "spreads", "totals")
    assert plan[0].intended_game_ids == (1, 2)


def test_plan_deduplicates_provider_calls_and_excludes_credentials() -> None:
    game = _game(1)
    request = build_morning_plan((game,))[0]
    summary = acquisition_plan_summary((request, request), _Cache(), available_credits=20_000)  # type: ignore[arg-type]

    assert summary["logical_requests"] == 2
    assert summary["unique_provider_requests"] == 1
    assert summary["expected_new_credits"] == 30
    assert "api" not in json.dumps(summary["requests"]).casefold()


def test_existing_full_market_snapshot_satisfies_subset_request(tmp_path: Path) -> None:
    game = _game(1)
    full = build_morning_plan((game,))[0]
    payload = _payload(game, full.requested_at)
    from app.research.ncaaf.historical_odds_audit import HistoricalAuditStore

    HistoricalAuditStore(tmp_path).put(
        full,
        HistoricalOddsResponse(
            requested_at=full.requested_at,
            retrieved_at=datetime(2026, 8, 30, tzinfo=UTC),
            payload_bytes=json.dumps(payload).encode(),
            payload=payload,
            usage={},
        ),
    )
    subset = replace(full, markets=("spreads", "totals"), request_id="subset")

    cached = HistoricalMarketCache(tmp_path).find(subset)

    assert cached is not None
    assert cached.request_hash == full.request_hash


def test_later_sample_is_deterministic_stratified_and_bounded(tmp_path: Path) -> None:
    games = []
    game_id = 1
    for season in range(2020, 2025):
        for week, season_type in ((2, "regular"), (6, "regular"), (11, "regular"), (16, "postseason")):
            for hour in (17, 21, 1):
                games.append(
                    _game(
                        game_id,
                        season=season,
                        week=week,
                        season_type=season_type,
                        kickoff=datetime(season, 9 if week < 16 else 12, 7, hour, tzinfo=UTC),
                    )
                )
                game_id += 1

    selected = select_later_robustness_games(games)
    assert selected == select_later_robustness_games(tuple(reversed(games)))
    assert len(selected) == 40
    plan = build_later_plan(games, tmp_path)
    summary = acquisition_plan_summary(plan, _Cache(), available_credits=20_000)  # type: ignore[arg-type]
    assert summary["unique_provider_requests"] <= LATER_NEW_CALL_LIMIT
    assert summary["expected_new_credits"] <= 2_700


def test_holdout_year_cannot_enter_market_game_loader(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="2020-2024"):
        load_market_games(tmp_path, 2020, 2025)


def test_cache_validation_rejects_future_and_out_of_tolerance_snapshots() -> None:
    request = build_morning_plan((_game(1),))[0]
    future = _cached(request, {"timestamp": (request.requested_at + timedelta(seconds=1)).isoformat(), "data": []})
    stale = _cached(request, {"timestamp": (request.requested_at - timedelta(minutes=6)).isoformat(), "data": []})

    assert "future snapshot" in validate_cached_plan((request,), _Cache({request.request_hash: future}))[0]  # type: ignore[arg-type]
    assert "outside" in validate_cached_plan((request,), _Cache({request.request_hash: stale}))[0]  # type: ignore[arg-type]


class _Client:
    def __init__(self, game: MarketGame, remaining: int) -> None:
        self.game = game
        self.remaining = remaining
        self.used = 0
        self.fetches = 0

    def usage(self) -> dict[str, int]:
        return {"requests_remaining": self.remaining - self.used, "requests_used": self.used}

    def fetch(self, requested_at: datetime, *, markets: tuple[str, ...]) -> HistoricalOddsResponse:
        self.fetches += 1
        self.used += len(markets) * 10
        payload = _payload(self.game, requested_at)
        return HistoricalOddsResponse(
            requested_at=requested_at,
            retrieved_at=datetime(2026, 8, 30, tzinfo=UTC),
            payload_bytes=json.dumps(payload).encode(),
            payload=payload,
            usage={},
        )


def test_execution_is_resumable_and_enforces_credit_reserve() -> None:
    game = _game(1)
    request = build_morning_plan((game,))[0]
    cache = _Cache()
    client = _Client(game, 6_000)

    _, first = execute_plan((request,), client, cache, credit_limit=30)  # type: ignore[arg-type]
    _, second = execute_plan((request,), client, cache, credit_limit=30)  # type: ignore[arg-type]

    assert first["network_calls"] == 1
    assert second["network_calls"] == 0
    assert client.fetches == 1
    with pytest.raises(RuntimeError, match="5000-credit reserve"):
        execute_plan((request,), _Client(game, 5_020), _Cache(), credit_limit=30)  # type: ignore[arg-type]


def test_normalization_preserves_book_rows_exact_lines_and_is_deterministic(tmp_path: Path) -> None:
    game = _game(1)
    request = build_morning_plan((game,))[0]
    responses = {request.request_id: _cached(request, _payload(game, request.requested_at))}

    first = build_historical_market_dataset(
        tmp_path,
        (game,),
        (request,),
        responses,
        acquisition_plan_hashes=("plan",),
    )
    second = build_historical_market_dataset(
        tmp_path,
        (game,),
        (request,),
        responses,
        acquisition_plan_hashes=("plan",),
    )

    assert first["dataset_version"] == DATASET_VERSION
    assert first["dataset_hash"] == second["dataset_hash"]
    assert first["row_count"] == 18
    assert first["group_count"] == 3
    assert not validate_historical_market_dataset(tmp_path, first)


def test_minimum_supported_book_depth_is_explicit(tmp_path: Path) -> None:
    game = _game(1)
    request = build_morning_plan((game,))[0]
    responses = {request.request_id: _cached(request, _payload(game, request.requested_at, books=1))}
    manifest = build_historical_market_dataset(
        tmp_path,
        (game,),
        (request,),
        responses,
        acquisition_plan_hashes=("plan",),
    )
    from app.research.ncaaf.artifacts import ResearchArtifactStore

    store = ResearchArtifactStore(tmp_path)
    groups = [
        row
        for artifact in manifest["artifacts"]
        if artifact["dataset"] == "groups" and artifact["season"] == 2024
        for row in store.read_table(artifact["uri"]).to_pylist()
    ]
    assert all(not row["usable"] for row in groups)
    assert all(row["unusable_reasons"] == "insufficient_supported_complete_books" for row in groups)


def test_known_schedule_aliases_normalize_moneyline_and_spread_sides(tmp_path: Path) -> None:
    game = replace(_game(1), home_team="Mississippi")
    request = build_morning_plan((game,))[0]
    payload = _payload(game, request.requested_at, books=2)
    for book in payload["data"][0]["bookmakers"]:
        for market in book["markets"][:2]:
            market["outcomes"][0]["name"] = "Ole Miss"
    manifest = build_historical_market_dataset(
        tmp_path,
        (game,),
        (request,),
        {request.request_id: _cached(request, payload)},
        acquisition_plan_hashes=("plan",),
    )
    from app.research.ncaaf.artifacts import ResearchArtifactStore

    groups = [
        row
        for artifact in manifest["artifacts"]
        if artifact["dataset"] == "groups" and artifact["season"] == 2024
        for row in ResearchArtifactStore(tmp_path).read_table(artifact["uri"]).to_pylist()
    ]
    assert all(row["usable"] for row in groups)
