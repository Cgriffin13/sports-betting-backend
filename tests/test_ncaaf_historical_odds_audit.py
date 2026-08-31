from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.providers.odds_api_historical import HistoricalOddsClient, HistoricalOddsResponse
from app.research.ncaaf.historical_odds_audit import (
    AUTHORIZED_CREDIT_CEILING,
    AuditGame,
    CachedResponse,
    HistoricalAuditStore,
    SLATES,
    analyze_audit,
    audit_market,
    build_audit_plan,
    execute_audit,
    manifest_is_secret_safe,
    plan_summary,
    reconcile_event,
    report_for_commit,
    timestamp_distance_seconds,
    timestamp_is_eligible,
)


def _games() -> tuple[AuditGame, ...]:
    games: list[AuditGame] = []
    for slate in SLATES:
        local_kickoff = time(11 if slate.season == 2024 and slate.phase == "postseason" else 12)
        kickoff = datetime.combine(
            slate.slate_date, local_kickoff, ZoneInfo("America/New_York")
        ).astimezone(UTC)
        for index, game_id in enumerate(slate.anchor_game_ids):
            games.append(
                AuditGame(
                    provider_game_id=game_id,
                    canonical_event_id=f"canonical-{game_id}",
                    season=slate.season,
                    week=1,
                    season_type="postseason" if slate.phase == "postseason" else "regular",
                    kickoff=kickoff + timedelta(hours=index),
                    home_team=f"Home {game_id}",
                    away_team=f"Away {game_id}",
                    home_classification="fbs",
                    away_classification="fcs" if index else "fbs",
                    home_conference="Major",
                    away_conference="Other",
                    model_eligible=index == 0,
                )
            )
    return tuple(games)


def _book(key: str, game: AuditGame) -> dict[str, Any]:
    return {
        "key": key,
        "title": key,
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


def _event(game: AuditGame) -> dict[str, Any]:
    return {
        "id": f"odds-{game.provider_game_id}",
        "commence_time": game.kickoff.isoformat().replace("+00:00", "Z"),
        "home_team": game.home_team,
        "away_team": game.away_team,
        "bookmakers": [_book(key, game) for key in ("draftkings", "fanduel", "betmgm")],
    }


def test_request_plan_is_frozen_bounded_and_excludes_2025() -> None:
    requests = build_audit_plan(_games())
    summary = plan_summary(requests)

    assert summary["logical_requests"] == 76
    assert summary["normal_requests"] == 72
    assert summary["boundary_probes"] == 4
    assert summary["authorized_credit_ceiling"] == AUTHORIZED_CREDIT_CEILING == 2_280
    assert summary["expected_maximum_credits_after_deduplication"] <= 2_280
    assert summary["unique_billable_requests_after_cache_deduplication"] == 67
    assert summary["expected_maximum_credits_after_deduplication"] == 2_010
    assert all(request.season != 2025 and "2025" not in request.slate_date for request in requests)


def test_timestamp_distance_and_closest_prior_tolerances() -> None:
    requested_2020 = datetime(2020, 9, 26, 13, 0, tzinfo=UTC)
    assert timestamp_distance_seconds(requested_2020, requested_2020 - timedelta(minutes=10)) == 600
    assert timestamp_is_eligible(requested_2020, requested_2020 - timedelta(minutes=10))
    assert not timestamp_is_eligible(requested_2020, requested_2020 - timedelta(minutes=10, seconds=1))
    requested_2024 = datetime(2024, 9, 7, 13, 0, tzinfo=UTC)
    assert timestamp_is_eligible(requested_2024, requested_2024 - timedelta(minutes=5))
    assert not timestamp_is_eligible(requested_2024, requested_2024 + timedelta(seconds=1))


def test_event_reconciliation_requires_orientation_time_and_uniqueness() -> None:
    game = _games()[0]
    event = _event(game)
    assert reconcile_event(game, [event]) == ("reliable", event)

    reversed_event = {**event, "home_team": game.away_team, "away_team": game.home_team}
    assert reconcile_event(game, [reversed_event]) == ("missing", None)
    assert reconcile_event(game, [event, dict(event)]) == ("ambiguous", None)


def test_market_completeness_checks_both_sides_and_exact_lines() -> None:
    game = _games()[0]
    event = _event(game)
    assert audit_market(event, game, "h2h")["supported_complete_book_count"] == 3
    assert audit_market(event, game, "spreads")["line_complete"]
    assert audit_market(event, game, "totals")["line_complete"]

    broken = json.loads(json.dumps(event))
    broken["bookmakers"][0]["markets"][1]["outcomes"][1]["point"] = 4.0
    spread = audit_market(broken, game, "spreads")
    assert spread["complete_book_count"] == 2
    assert "draftkings" not in spread["complete_books"]


class _Response:
    status_code = 200
    headers = {"x-requests-used": "30", "x-requests-remaining": "9970", "x-requests-last": "30"}

    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload).encode()


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> _Response:
        self.calls.append((url, params))
        return _Response({"timestamp": params.get("date"), "data": []})


def test_provider_parses_wrapper_and_keeps_credential_out_of_result() -> None:
    session = _Session()
    client = HistoricalOddsClient("test-credential", session=session)  # type: ignore[arg-type]
    response = client.fetch(datetime(2024, 9, 7, 13, 0, tzinfo=UTC))

    assert response.returned_snapshot_at == datetime(2024, 9, 7, 13, 0, tzinfo=UTC)
    assert response.usage["requests_last"] == 30
    assert session.calls[0][1]["apiKey"] == "test-credential"
    assert "test-credential" not in json.dumps(response.payload)


def test_immutable_manifest_and_request_hash_exclude_credential(tmp_path: Path) -> None:
    request = build_audit_plan(_games())[0]
    payload = {"timestamp": request.requested_at.isoformat(), "data": []}
    raw = json.dumps(payload).encode()
    stored = HistoricalAuditStore(tmp_path).put(
        request,
        HistoricalOddsResponse(
            requested_at=request.requested_at,
            retrieved_at=datetime(2026, 8, 30, tzinfo=UTC),
            payload_bytes=raw,
            payload=payload,
            usage={"requests_last": 30},
        ),
    )

    assert manifest_is_secret_safe(stored.manifest)
    assert "api" not in request.safe_parameters
    assert "credential" not in json.dumps(stored.manifest).casefold()
    assert HistoricalAuditStore(tmp_path).load(request) is not None


def test_aggregate_reporting_is_deterministic() -> None:
    games = _games()
    requests = build_audit_plan(games)
    events = [_event(game) for game in games]
    responses: dict[str, CachedResponse] = {}
    for request in requests:
        payload = {"timestamp": request.requested_at.isoformat(), "data": events}
        responses[request.request_hash] = CachedResponse(
            request_hash=request.request_hash,
            content_hash="a" * 64,
            retrieved_at=datetime(2026, 8, 30, tzinfo=UTC),
            payload=payload,
            manifest={},
            cache_hit=False,
        )
    execution = {"logical_requests": 76, "historical_network_requests": len(responses), "credits_consumed": 0}
    first = analyze_audit(requests, games, responses, execution)
    second = analyze_audit(requests, games, responses, execution)

    assert first["report_hash"] == second["report_hash"]
    assert report_for_commit(first) == report_for_commit(second)
    assert first["decision"]["status"] == "GO"


class _InsufficientCreditClient:
    def usage(self) -> dict[str, int]:
        return {"requests_remaining": 2_000, "requests_used": 0, "requests_last": 0}

    def fetch(self, requested_at: datetime) -> HistoricalOddsResponse:
        raise AssertionError(f"billable fetch must not occur during failed preflight: {requested_at}")


def test_preflight_rejects_insufficient_credits_before_historical_call(tmp_path: Path) -> None:
    requests = build_audit_plan(_games())

    with pytest.raises(RuntimeError, match="requires up to 2010 credits"):
        execute_audit(
            requests,
            _InsufficientCreditClient(),  # type: ignore[arg-type]
            HistoricalAuditStore(tmp_path),
        )
