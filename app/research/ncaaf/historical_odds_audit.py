from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from app.providers.odds_api_historical import HistoricalOddsClient, HistoricalOddsResponse, iso_z, parse_iso_timestamp
from app.research.ncaaf.contracts import stable_hash

AUDIT_VERSION = "ncaaf-historical-odds-coverage-audit-v1"
AVAILABILITY_POLICY_VERSION = "the-odds-api-provider-archive-snapshot-v1"
REPORT_VERSION = "ncaaf-historical-odds-audit-report-v1"
MARKETS = ("h2h", "spreads", "totals")
SUPPORTED_BOOKS = frozenset({"draftkings", "fanduel", "betmgm"})
EASTERN = ZoneInfo("America/New_York")
MAX_CREDITS_PER_REQUEST = 30
AUTHORIZED_LOGICAL_REQUESTS = 76
AUTHORIZED_CREDIT_CEILING = 2_280
PRE_FIVE_MINUTE_CADENCE = datetime(2022, 9, 18, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class AuditTolerancePolicy:
    version: str = "historical-odds-coverage-tolerances-v1"
    pre_2022_09_18_snapshot_minutes: int = 10
    later_snapshot_minutes: int = 5
    reliable_kickoff_distance_minutes: int = 30
    minimum_supported_complete_books: int = 2
    overall_usable_coverage: float = 0.80
    each_season_usable_coverage: float = 0.70
    overall_two_book_coverage: float = 0.75
    paired_book_completeness: float = 0.95
    maximum_ambiguous_mapping_rate: float = 0.02
    timestamp_fidelity_rate: float = 0.99


TOLERANCES = AuditTolerancePolicy()


@dataclass(frozen=True, slots=True)
class SlateDefinition:
    season: int
    slate_date: date
    phase: str
    anchor_game_ids: tuple[int, int]


SLATES = (
    SlateDefinition(2020, date(2020, 9, 26), "early_regular", (401236253, 401237035)),
    SlateDefinition(2020, date(2020, 11, 28), "late_regular", (401247333, 401207191)),
    SlateDefinition(2020, date(2021, 1, 2), "postseason", (401256109, 401256112)),
    SlateDefinition(2022, date(2022, 9, 10), "early_regular", (401403868, 401403982)),
    SlateDefinition(2022, date(2022, 11, 26), "late_regular", (401405153, 401426617)),
    SlateDefinition(2022, date(2022, 12, 31), "postseason", (401442017, 401442015)),
    SlateDefinition(2024, date(2024, 9, 7), "early_regular", (401628347, 401628348)),
    SlateDefinition(2024, date(2024, 11, 30), "late_regular", (401628566, 401640988)),
    SlateDefinition(2024, date(2024, 12, 28), "postseason", (401677094, 401677097)),
)


@dataclass(frozen=True, slots=True)
class AuditGame:
    provider_game_id: int
    canonical_event_id: str | None
    season: int
    week: int | None
    season_type: str
    kickoff: datetime
    home_team: str
    away_team: str
    home_classification: str | None
    away_classification: str | None
    home_conference: str | None
    away_conference: str | None
    model_eligible: bool


@dataclass(frozen=True, slots=True)
class AuditRequest:
    request_id: str
    season: int
    slate_date: str
    slate_phase: str
    request_kind: str
    horizon: str
    requested_at: datetime
    intended_game_ids: tuple[int, ...]
    anchor_game_id: int | None = None

    @property
    def safe_parameters(self) -> dict[str, Any]:
        return {
            "sport": "americanfootball_ncaaf",
            "regions": "us",
            "markets": list(MARKETS),
            "odds_format": "american",
            "date_format": "iso",
            "date": iso_z(self.requested_at),
        }

    @property
    def request_hash(self) -> str:
        return stable_hash({"provider": "the_odds_api", "endpoint": "historical_odds", **self.safe_parameters})


@dataclass(frozen=True, slots=True)
class CachedResponse:
    request_hash: str
    content_hash: str
    retrieved_at: datetime
    payload: dict[str, Any]
    manifest: dict[str, Any]
    cache_hit: bool


class HistoricalAuditStore:
    def __init__(self, root: Path) -> None:
        self.root = (root / "odds-audit-v1").resolve()

    def load(self, request: AuditRequest) -> CachedResponse | None:
        pointer = self.root / "r" / request.request_hash[:20] / "current.json"
        if not pointer.is_file():
            return None
        current = json.loads(pointer.read_text(encoding="utf-8"))
        manifest_path = self.root / current["manifest_uri"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = (self.root / manifest["artifact_uri"]).resolve()
        if not artifact.is_relative_to(self.root) or not artifact.is_file():
            return None
        raw = gzip.decompress(artifact.read_bytes())
        if hashlib.sha256(raw).hexdigest() != manifest["content_hash"]:
            raise ValueError("cached historical odds artifact hash mismatch")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("cached historical odds artifact has invalid shape")
        return CachedResponse(
            request_hash=request.request_hash,
            content_hash=manifest["content_hash"],
            retrieved_at=_required_timestamp(manifest["retrieved_at"]),
            payload=payload,
            manifest=manifest,
            cache_hit=True,
        )

    def put(self, request: AuditRequest, response: HistoricalOddsResponse) -> CachedResponse:
        content_hash = hashlib.sha256(response.payload_bytes).hexdigest()
        request_dir = self.root / "r" / request.request_hash[:20]
        existing = self.load(request)
        artifact = self.root / "a" / request.request_hash[:20] / f"{content_hash}.json.gz"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if not artifact.exists():
            _atomic_bytes(artifact, gzip.compress(response.payload_bytes, mtime=0))
        manifest: dict[str, Any] = {
            "audit_version": AUDIT_VERSION,
            "provider": "the_odds_api",
            "endpoint": "historical/sports/americanfootball_ncaaf/odds",
            "request_parameters": request.safe_parameters,
            "request_hash": request.request_hash,
            "retrieved_at": response.retrieved_at.isoformat(),
            "requested_snapshot_at": iso_z(request.requested_at),
            "returned_snapshot_at": _iso_or_none(response.returned_snapshot_at),
            "previous_snapshot_at": response.payload.get("previous_timestamp"),
            "next_snapshot_at": response.payload.get("next_timestamp"),
            "content_hash": content_hash,
            "schema_version": "the-odds-api-historical-v4",
            "row_count": len(response.payload.get("data", [])),
            "response_bytes": len(response.payload_bytes),
            "stored_bytes": artifact.stat().st_size,
            "availability_mode": "provider_archive",
            "availability_policy_version": AVAILABILITY_POLICY_VERSION,
            "response_metadata": response.usage,
            "warnings": [],
            "errors": [],
            "supersedes_content_hash": existing.content_hash if existing and existing.content_hash != content_hash else None,
            "artifact_uri": artifact.relative_to(self.root).as_posix(),
        }
        manifest_path = self.root / "m" / request.request_hash[:20] / f"{content_hash}.json"
        _atomic_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        _atomic_text(
            request_dir / "current.json",
            json.dumps({"manifest_uri": manifest_path.relative_to(self.root).as_posix()}, sort_keys=True) + "\n",
        )
        return CachedResponse(
            request_hash=request.request_hash,
            content_hash=content_hash,
            retrieved_at=response.retrieved_at,
            payload=response.payload,
            manifest=manifest,
            cache_hit=False,
        )


def load_audit_games(root: Path) -> tuple[AuditGame, ...]:
    pointer = json.loads((root / "normalized" / "current.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / pointer["uri"]).read_text(encoding="utf-8"))
    games: list[AuditGame] = []
    columns = [field.name for field in AuditGame.__dataclass_fields__.values()]
    for season in (2020, 2022, 2024):
        artifact = next(
            item for item in manifest["artifacts"] if item["dataset"] == "games" and item["season"] == season
        )
        rows = pq.ParquetFile(root / artifact["uri"]).read(columns=columns).to_pylist()
        for row in rows:
            games.append(AuditGame(**row))
    return tuple(games)


def build_audit_plan(games: Sequence[AuditGame]) -> tuple[AuditRequest, ...]:
    by_id = {game.provider_game_id: game for game in games}
    requests: list[AuditRequest] = []
    for slate in SLATES:
        slate_games = tuple(
            sorted(
                (
                    game
                    for game in games
                    if game.season == slate.season
                    and game.kickoff.astimezone(EASTERN).date() == slate.slate_date
                    and "fbs" in {game.home_classification, game.away_classification}
                ),
                key=lambda game: (game.kickoff, game.provider_game_id),
            )
        )
        if not slate_games:
            raise ValueError(f"no local schedule games for slate {slate.slate_date}")
        anchors = tuple(by_id.get(game_id) for game_id in slate.anchor_game_ids)
        if any(game is None for game in anchors):
            raise ValueError(f"missing frozen anchor for slate {slate.slate_date}")
        first_kickoff = min(game.kickoff for game in slate_games)
        fixed_morning = datetime.combine(slate.slate_date, time(9), EASTERN).astimezone(UTC)
        relative_morning = first_kickoff - timedelta(hours=3)
        intended = tuple(game.provider_game_id for game in slate_games)
        for horizon, timestamp in (
            ("morning_fixed_0900_et", fixed_morning),
            ("morning_first_kickoff_minus_3h", relative_morning),
        ):
            requests.append(
                AuditRequest(
                    request_id=f"{slate.season}-{slate.phase}-{horizon}",
                    season=slate.season,
                    slate_date=slate.slate_date.isoformat(),
                    slate_phase=slate.phase,
                    request_kind="normal",
                    horizon=horizon,
                    requested_at=timestamp,
                    intended_game_ids=intended,
                )
            )
        for anchor in anchors:
            assert anchor is not None
            for horizon, delta in (
                ("24_hours_before_kickoff", timedelta(hours=24)),
                ("60_minutes_before_kickoff", timedelta(minutes=60)),
                ("near_close_5_minutes", timedelta(minutes=5)),
            ):
                requests.append(
                    AuditRequest(
                        request_id=f"{slate.season}-{slate.phase}-{anchor.provider_game_id}-{horizon}",
                        season=slate.season,
                        slate_date=slate.slate_date.isoformat(),
                        slate_phase=slate.phase,
                        request_kind="normal",
                        horizon=horizon,
                        requested_at=anchor.kickoff - delta,
                        intended_game_ids=(anchor.provider_game_id,),
                        anchor_game_id=anchor.provider_game_id,
                    )
                )
    probe_base = datetime(2024, 9, 7, 13, 0, tzinfo=UTC)
    for label, timestamp in (
        ("before_grid", probe_base - timedelta(seconds=1)),
        ("at_grid", probe_base),
        ("after_grid", probe_base + timedelta(seconds=1)),
        ("next_grid", probe_base + timedelta(minutes=5)),
    ):
        requests.append(
            AuditRequest(
                request_id=f"2024-boundary-{label}",
                season=2024,
                slate_date="2024-09-07",
                slate_phase="boundary_probe",
                request_kind="boundary_probe",
                horizon=f"boundary_{label}",
                requested_at=timestamp,
                intended_game_ids=(),
            )
        )
    validate_plan(requests)
    return tuple(requests)


def validate_plan(requests: Sequence[AuditRequest]) -> None:
    normal = sum(request.request_kind == "normal" for request in requests)
    probes = sum(request.request_kind == "boundary_probe" for request in requests)
    if (normal, probes, len(requests)) != (72, 4, AUTHORIZED_LOGICAL_REQUESTS):
        raise ValueError("historical odds plan must remain exactly 72 normal plus four boundary requests")
    if any(request.season == 2025 or "2025" in request.slate_date for request in requests):
        raise ValueError("locked 2025 holdout cannot enter the odds audit")
    if AUTHORIZED_LOGICAL_REQUESTS * MAX_CREDITS_PER_REQUEST != AUTHORIZED_CREDIT_CEILING:
        raise ValueError("historical audit credit ceiling changed")


def plan_summary(requests: Sequence[AuditRequest]) -> dict[str, Any]:
    validate_plan(requests)
    unique = {request.request_hash for request in requests}
    return {
        "audit_version": AUDIT_VERSION,
        "mode": "plan",
        "logical_requests": len(requests),
        "normal_requests": 72,
        "boundary_probes": 4,
        "unique_billable_requests_after_cache_deduplication": len(unique),
        "maximum_credits_per_request": MAX_CREDITS_PER_REQUEST,
        "expected_maximum_credits_after_deduplication": len(unique) * MAX_CREDITS_PER_REQUEST,
        "authorized_credit_ceiling": AUTHORIZED_CREDIT_CEILING,
        "tolerances": asdict(TOLERANCES),
        "requests": [request_to_dict(request) for request in requests],
    }


def execute_audit(
    requests: Sequence[AuditRequest], client: HistoricalOddsClient, store: HistoricalAuditStore
) -> tuple[dict[str, CachedResponse], dict[str, Any]]:
    validate_plan(requests)
    before = client.usage()
    uncached_hashes = {request.request_hash for request in requests if store.load(request) is None}
    expected_remaining_ceiling = len(uncached_hashes) * MAX_CREDITS_PER_REQUEST
    available = before.get("requests_remaining")
    if isinstance(available, int) and available < expected_remaining_ceiling:
        raise RuntimeError(
            f"historical audit requires up to {expected_remaining_ceiling} credits but only {available} remain; "
            "no historical request was made"
        )
    responses: dict[str, CachedResponse] = {}
    network_calls = 0
    cache_hits = 0
    for request in requests:
        cached = store.load(request)
        if cached is not None:
            responses[request.request_hash] = cached
            cache_hits += 1
            continue
        fetched = client.fetch(request.requested_at)
        responses[request.request_hash] = store.put(request, fetched)
        network_calls += 1
    after = client.usage()
    credits = _usage_delta(before, after)
    if credits is not None and credits > AUTHORIZED_CREDIT_CEILING:
        raise RuntimeError("provider accounting exceeded the authorized historical audit ceiling")
    execution = {
        "audit_version": AUDIT_VERSION,
        "logical_requests": len(requests),
        "unique_responses": len(responses),
        "historical_network_requests": network_calls,
        "logical_cache_hits": cache_hits,
        "preflight_expected_credit_ceiling": expected_remaining_ceiling,
        "usage_before": before,
        "usage_after": after,
        "credits_consumed": credits,
    }
    return responses, execution


def analyze_audit(
    requests: Sequence[AuditRequest],
    games: Sequence[AuditGame],
    responses: Mapping[str, CachedResponse],
    execution: Mapping[str, Any],
) -> dict[str, Any]:
    by_id = {game.provider_game_id: game for game in games}
    records: list[dict[str, Any]] = []
    boundary: list[dict[str, Any]] = []
    event_ids: dict[int, set[str]] = defaultdict(set)
    for request in requests:
        response = responses[request.request_hash]
        returned = parse_iso_timestamp(response.payload.get("timestamp"))
        distance = timestamp_distance_seconds(request.requested_at, returned)
        fidelity = timestamp_is_eligible(request.requested_at, returned)
        if request.request_kind == "boundary_probe":
            boundary.append(
                {
                    "request_id": request.request_id,
                    "requested_at": iso_z(request.requested_at),
                    "returned_snapshot_at": _iso_or_none(returned),
                    "distance_seconds": distance,
                    "previous_snapshot_at": response.payload.get("previous_timestamp"),
                    "next_snapshot_at": response.payload.get("next_timestamp"),
                    "at_or_before": returned is not None and returned <= request.requested_at,
                }
            )
            continue
        raw_events = [item for item in response.payload.get("data", []) if isinstance(item, dict)]
        for game_id in request.intended_game_ids:
            game = by_id[game_id]
            match_status, event = reconcile_event(game, raw_events)
            provider_event_id = event.get("id") if event else None
            if isinstance(provider_event_id, str):
                event_ids[game_id].add(provider_event_id)
            for market in MARKETS:
                audit = audit_market(event, game, market) if event else _empty_market_audit()
                reasons: list[str] = []
                if match_status != "reliable":
                    reasons.append(f"event_mapping_{match_status}")
                if not fidelity:
                    reasons.append("snapshot_timestamp_outside_tolerance")
                if audit["supported_complete_book_count"] < TOLERANCES.minimum_supported_complete_books:
                    reasons.append("insufficient_supported_complete_books")
                records.append(
                    {
                        "request_id": request.request_id,
                        "season": request.season,
                        "slate_date": request.slate_date,
                        "slate_phase": request.slate_phase,
                        "horizon": request.horizon,
                        "market": market,
                        "cfbd_game_id": game.provider_game_id,
                        "canonical_event_id": game.canonical_event_id,
                        "home_team": game.home_team,
                        "away_team": game.away_team,
                        "kickoff": iso_z(game.kickoff),
                        "cohort": "fbs_vs_fbs" if game.model_eligible else "fbs_context",
                        "requested_at": iso_z(request.requested_at),
                        "returned_snapshot_at": _iso_or_none(returned),
                        "timestamp_distance_seconds": distance,
                        "timestamp_eligible": fidelity,
                        "mapping_status": match_status,
                        "provider_event_id": provider_event_id,
                        **audit,
                        "usable": not reasons,
                        "unusable_reasons": reasons,
                    }
                )
    event_stability = {
        str(game_id): {"provider_event_ids": sorted(values), "stable": len(values) == 1}
        for game_id, values in sorted(event_ids.items())
    }
    summaries = _aggregate_records(records)
    approved = _approved_horizon_markets(summaries)
    morning = _morning_recommendation(summaries, requests)
    decision = _decision(approved)
    report = {
        "report_version": REPORT_VERSION,
        "audit_version": AUDIT_VERSION,
        "availability_policy_version": AVAILABILITY_POLICY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "tolerances": asdict(TOLERANCES),
        "execution": dict(execution),
        "slates": [slate_to_dict(slate) for slate in SLATES],
        "boundary_probes": boundary,
        "event_id_stability": event_stability,
        "summary": summaries,
        "approved_horizon_markets": approved,
        "morning_recommendation": morning,
        "decision": decision,
        "records": records,
    }
    deterministic = {key: value for key, value in report.items() if key != "generated_at"}
    report["report_hash"] = stable_hash(deterministic)
    return report


def timestamp_distance_seconds(requested: datetime, returned: datetime | None) -> int | None:
    if requested.tzinfo is None:
        raise ValueError("requested timestamp must be timezone-aware")
    if returned is None:
        return None
    if returned.tzinfo is None:
        raise ValueError("returned timestamp must be timezone-aware")
    return int(abs((requested.astimezone(UTC) - returned.astimezone(UTC)).total_seconds()))


def timestamp_is_eligible(requested: datetime, returned: datetime | None) -> bool:
    if returned is None or returned > requested:
        return False
    maximum = 10 * 60 if requested < PRE_FIVE_MINUTE_CADENCE else 5 * 60
    distance = timestamp_distance_seconds(requested, returned)
    return distance is not None and distance <= maximum


def reconcile_event(game: AuditGame, events: Sequence[Mapping[str, Any]]) -> tuple[str, Mapping[str, Any] | None]:
    candidates: list[Mapping[str, Any]] = []
    for event in events:
        kickoff = parse_iso_timestamp(event.get("commence_time"))
        if kickoff is None:
            continue
        kickoff_distance = abs((kickoff - game.kickoff.astimezone(UTC)).total_seconds()) / 60
        if kickoff_distance > TOLERANCES.reliable_kickoff_distance_minutes:
            continue
        if not _name_compatible(event.get("home_team"), game.home_team):
            continue
        if not _name_compatible(event.get("away_team"), game.away_team):
            continue
        candidates.append(event)
    if len(candidates) == 1:
        return "reliable", candidates[0]
    if len(candidates) > 1:
        return "ambiguous", None
    return "missing", None


def audit_market(event: Mapping[str, Any], game: AuditGame, market_key: str) -> dict[str, Any]:
    books: list[str] = []
    complete: list[str] = []
    supported_complete: list[str] = []
    for bookmaker in event.get("bookmakers", []):
        if not isinstance(bookmaker, dict):
            continue
        key = bookmaker.get("key")
        if not isinstance(key, str):
            continue
        market = next(
            (
                candidate
                for candidate in bookmaker.get("markets", [])
                if isinstance(candidate, dict) and candidate.get("key") == market_key
            ),
            None,
        )
        if market is None:
            continue
        books.append(key)
        if _market_complete(market, game, market_key):
            complete.append(key)
            if key in SUPPORTED_BOOKS:
                supported_complete.append(key)
    return {
        "book_count": len(set(books)),
        "complete_book_count": len(set(complete)),
        "supported_complete_book_count": len(set(supported_complete)),
        "books": sorted(set(books)),
        "complete_books": sorted(set(complete)),
        "supported_complete_books": sorted(set(supported_complete)),
        "paired_side_complete": bool(complete),
        "line_complete": bool(complete) if market_key in {"spreads", "totals"} else None,
    }


def _market_complete(market: Mapping[str, Any], game: AuditGame, market_key: str) -> bool:
    outcomes = [item for item in market.get("outcomes", []) if isinstance(item, dict)]
    if len(outcomes) != 2 or any(not _valid_odds(item.get("price")) for item in outcomes):
        return False
    if market_key == "h2h":
        return _opposing_teams(outcomes, game)
    if market_key == "spreads":
        if not _opposing_teams(outcomes, game):
            return False
        left = _finite_number(outcomes[0].get("point"))
        right = _finite_number(outcomes[1].get("point"))
        return left is not None and right is not None and math.isclose(left + right, 0.0, abs_tol=1e-9)
    names = {_normalized_name(item.get("name")) for item in outcomes}
    left = _finite_number(outcomes[0].get("point"))
    right = _finite_number(outcomes[1].get("point"))
    return names == {"over", "under"} and left is not None and right is not None and math.isclose(
        left, right, abs_tol=1e-9
    )


def _opposing_teams(outcomes: Sequence[Mapping[str, Any]], game: AuditGame) -> bool:
    return any(_name_compatible(item.get("name"), game.home_team) for item in outcomes) and any(
        _name_compatible(item.get("name"), game.away_team) for item in outcomes
    )


def _aggregate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    overall: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    primary_grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    primary_overall: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    cohort_grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    slate_grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        season_horizon_market = (str(record["season"]), str(record["horizon"]), str(record["market"]))
        horizon_market = (str(record["horizon"]), str(record["market"]))
        grouped[season_horizon_market].append(record)
        overall[horizon_market].append(record)
        cohort_grouped[(str(record["cohort"]), *horizon_market)].append(record)
        slate_grouped[
            (str(record["season"]), str(record["slate_phase"]), *horizon_market)
        ].append(record)
        if record["cohort"] == "fbs_vs_fbs":
            primary_grouped[season_horizon_market].append(record)
            primary_overall[horizon_market].append(record)
    return {
        "by_season_horizon_market": {
            "|".join(key): _aggregate_group(values) for key, values in sorted(grouped.items())
        },
        "by_horizon_market": {"|".join(key): _aggregate_group(values) for key, values in sorted(overall.items())},
        "primary_fbs_vs_fbs_by_season_horizon_market": {
            "|".join(key): _aggregate_group(values) for key, values in sorted(primary_grouped.items())
        },
        "primary_fbs_vs_fbs_by_horizon_market": {
            "|".join(key): _aggregate_group(values) for key, values in sorted(primary_overall.items())
        },
        "by_cohort_horizon_market": {
            "|".join(key): _aggregate_group(values) for key, values in sorted(cohort_grouped.items())
        },
        "by_slate_horizon_market": {
            "|".join(key): _aggregate_group(values) for key, values in sorted(slate_grouped.items())
        },
    }


def _aggregate_group(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(records)
    usable = sum(bool(item["usable"]) for item in records)
    distances = sorted(
        int(item["timestamp_distance_seconds"])
        for item in records
        if item["timestamp_distance_seconds"] is not None
    )
    book_counts = sorted(int(item["supported_complete_book_count"]) for item in records)
    total_books = sum(int(item["book_count"]) for item in records)
    total_complete = sum(int(item["complete_book_count"]) for item in records)
    reasons: Counter[str] = Counter()
    books: Counter[str] = Counter()
    for item in records:
        reasons.update(str(reason) for reason in item["unusable_reasons"])
        books.update(str(book) for book in item["complete_books"])
    return {
        "games_requested": count,
        "games_with_usable_market_snapshot": usable,
        "coverage_pct": _pct(usable, count),
        "median_timestamp_distance_seconds": _quantile(distances, 0.5),
        "p90_timestamp_distance_seconds": _quantile(distances, 0.9),
        "timestamp_fidelity_pct": _pct(sum(bool(item["timestamp_eligible"]) for item in records), count),
        "supported_complete_book_count_distribution": _distribution(book_counts),
        "pct_with_at_least_2_supported_books": _pct(sum(value >= 2 for value in book_counts), count),
        "pct_with_at_least_3_supported_books": _pct(sum(value >= 3 for value in book_counts), count),
        "paired_side_completeness_pct": _pct(total_complete, total_books),
        "line_completeness_pct": _pct(total_complete, total_books),
        "reliable_event_mappings": sum(item["mapping_status"] == "reliable" for item in records),
        "ambiguous_event_mappings": sum(item["mapping_status"] == "ambiguous" for item in records),
        "missing_event_mappings": sum(item["mapping_status"] == "missing" for item in records),
        "unusable_reasons": dict(sorted(reasons.items())),
        "complete_book_frequency": dict(sorted(books.items())),
    }


def _approved_horizon_markets(summary: Mapping[str, Any]) -> dict[str, bool]:
    # Phase 5B-7 evaluates the frozen FBS-vs-FBS model cohort. FBS/FCS rows remain
    # visible as context evidence but cannot veto a model-cohort horizon.
    overall = summary["primary_fbs_vs_fbs_by_horizon_market"]
    season = summary["primary_fbs_vs_fbs_by_season_horizon_market"]
    approved: dict[str, bool] = {}
    for key, metrics in overall.items():
        horizon, market = key.split("|")
        seasons = [
            value
            for season_key, value in season.items()
            if season_key.endswith(f"|{horizon}|{market}")
        ]
        mappings = metrics["games_requested"]
        ambiguous_rate = metrics["ambiguous_event_mappings"] / mappings if mappings else 1.0
        approved[key] = bool(
            metrics["coverage_pct"] >= TOLERANCES.overall_usable_coverage * 100
            and seasons
            and all(item["coverage_pct"] >= TOLERANCES.each_season_usable_coverage * 100 for item in seasons)
            and metrics["pct_with_at_least_2_supported_books"] >= TOLERANCES.overall_two_book_coverage * 100
            and metrics["paired_side_completeness_pct"] >= TOLERANCES.paired_book_completeness * 100
            and ambiguous_rate <= TOLERANCES.maximum_ambiguous_mapping_rate
            and metrics["timestamp_fidelity_pct"] >= TOLERANCES.timestamp_fidelity_rate * 100
        )
    return approved


def _morning_recommendation(
    summary: Mapping[str, Any], requests: Sequence[AuditRequest]
) -> dict[str, Any]:
    candidates: dict[str, float] = {}
    for horizon in ("morning_fixed_0900_et", "morning_first_kickoff_minus_3h"):
        values = [
            metrics["coverage_pct"]
            for key, metrics in summary["primary_fbs_vs_fbs_by_horizon_market"].items()
            if key.startswith(f"{horizon}|")
        ]
        candidates[horizon] = sum(values) / len(values) if values else 0.0
    winner = max(candidates, key=lambda key: (candidates[key], key == "morning_first_kickoff_minus_3h"))
    by_slate: dict[tuple[int, str], set[datetime]] = defaultdict(set)
    for request in requests:
        if request.horizon.startswith("morning_"):
            by_slate[(request.season, request.slate_phase)].add(request.requested_at)
    identical = sum(len(values) == 1 for values in by_slate.values())
    return {
        "coverage_by_candidate_pct": candidates,
        "slates_compared": len(by_slate),
        "slates_with_identical_candidate_timestamp": identical,
        "recommended_policy": winner,
        "recommendation_reason": (
            "Coverage tied; the relative convention guarantees a run before the first kickoff and remains "
            "well-defined when a slate starts earlier or later than noon Eastern."
        ),
    }


def _decision(approved: Mapping[str, bool]) -> dict[str, Any]:
    approved_keys = sorted(key for key, value in approved.items() if value)
    required_horizons = {
        "24_hours_before_kickoff",
        "60_minutes_before_kickoff",
        "near_close_5_minutes",
    }
    approved_horizons = {key.split("|")[0] for key in approved_keys}
    morning = any(horizon.startswith("morning_") for horizon in approved_horizons)
    every_required_pair = all(
        approved.get(f"{horizon}|{market}", False)
        for horizon in required_horizons
        for market in MARKETS
    )
    morning_all_markets = any(
        all(approved.get(f"{horizon}|{market}", False) for market in MARKETS)
        for horizon in approved_horizons
        if horizon.startswith("morning_")
    )
    if morning and morning_all_markets and every_required_pair:
        status = "GO"
    elif approved_keys:
        status = "CONDITIONAL GO"
    else:
        status = "NO-GO"
    return {
        "status": status,
        "approved_horizon_markets": approved_keys,
        "minimum_supported_complete_books": TOLERANCES.minimum_supported_complete_books,
        "larger_purchase_justified": status in {"GO", "CONDITIONAL GO"},
    }


def request_to_dict(request: AuditRequest) -> dict[str, Any]:
    value = asdict(request)
    value["requested_at"] = iso_z(request.requested_at)
    value["request_hash"] = request.request_hash
    value["expected_max_credits"] = MAX_CREDITS_PER_REQUEST
    return value


def slate_to_dict(slate: SlateDefinition) -> dict[str, Any]:
    value = asdict(slate)
    value["slate_date"] = slate.slate_date.isoformat()
    return value


def _name_compatible(provider_name: Any, schedule_name: str) -> bool:
    provider = _normalized_name(provider_name)
    schedule = _normalized_name(schedule_name)
    if not provider or not schedule:
        return False
    return provider == schedule or provider.startswith(f"{schedule} ") or schedule.startswith(f"{provider} ")


def _normalized_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    aliases = {"mississippi": "ole miss", "connecticut": "uconn", "massachusetts": "umass"}
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return aliases.get(normalized, normalized)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _valid_odds(value: Any) -> bool:
    number = _finite_number(value)
    return number is not None and number != 0


def _empty_market_audit() -> dict[str, Any]:
    return {
        "book_count": 0,
        "complete_book_count": 0,
        "supported_complete_book_count": 0,
        "books": [],
        "complete_books": [],
        "supported_complete_books": [],
        "paired_side_complete": False,
        "line_complete": False,
    }


def _pct(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 4) if denominator else 0.0


def _quantile(values: Sequence[int], probability: float) -> int | None:
    if not values:
        return None
    index = max(0, math.ceil(probability * len(values)) - 1)
    return int(values[index])


def _distribution(values: Sequence[int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "median": None, "p90": None, "max": None}
    return {"min": min(values), "median": median(values), "p90": _quantile(values, 0.9), "max": max(values)}


def _usage_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> int | None:
    before_used = before.get("requests_used")
    after_used = after.get("requests_used")
    if isinstance(before_used, int) and isinstance(after_used, int):
        return after_used - before_used
    before_remaining = before.get("requests_remaining")
    after_remaining = after.get("requests_remaining")
    if isinstance(before_remaining, int) and isinstance(after_remaining, int):
        return before_remaining - after_remaining
    return None


def _required_timestamp(value: Any) -> datetime:
    parsed = parse_iso_timestamp(value)
    if parsed is None:
        raise ValueError("manifest timestamp is invalid")
    return parsed


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else iso_z(value)


def _atomic_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{uuid4().hex}.tmp"
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{uuid4().hex}.tmp"
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def report_for_commit(report: Mapping[str, Any]) -> dict[str, Any]:
    """Remove per-game rows while retaining deterministic aggregate and decision evidence."""
    return {key: value for key, value in report.items() if key not in {"records", "generated_at"}}


def manifest_is_secret_safe(manifest: Mapping[str, Any]) -> bool:
    lowered = json.dumps(manifest, sort_keys=True, default=str).casefold()
    return not any(token in lowered for token in ("apikey", "api_key", "authorization", "bearer "))


def render_markdown_report(report: Mapping[str, Any]) -> str:
    execution = report["execution"]
    decision = report["decision"]
    lines = [
        "# NCAAF Historical Odds Coverage Audit",
        "",
        f"Status: **{decision['status']}** for Phase 5B-7 same-horizon market-aware evaluation under "
        f"`{report['audit_version']}`. This is a coverage audit, not evidence of model edge or profitability.",
        "",
        "## Execution and frozen policy",
        "",
        f"- Logical requests: `{execution['logical_requests']}`.",
        f"- Unique historical network requests: `{execution['historical_network_requests']}`.",
        f"- Credits consumed: `{execution['credits_consumed']}` (authorized ceiling: `{AUTHORIZED_CREDIT_CEILING}`).",
        f"- Provider credits before/after: `{execution['usage_before'].get('requests_remaining')}` / "
        f"`{execution['usage_after'].get('requests_remaining')}`.",
        "- Seasons: `2020`, `2022`, and `2024`; 2025 was excluded.",
        f"- Availability policy: `{report['availability_policy_version']}`.",
        f"- Minimum supported complete books: `{decision['minimum_supported_complete_books']}`.",
        "- Provider snapshots must be at or before the requested cutoff and within 10 minutes before "
        "2022-09-18 or 5 minutes thereafter.",
        "",
        "The Odds API credential was used only as a transport parameter. It was not printed, logged, persisted, "
        "hashed into a request identifier, included in a report, or committed.",
        "",
        "## Primary FBS-vs-FBS horizon and market coverage",
        "",
        "| Horizon | Market | Games | Usable | Coverage | Median / p90 timestamp distance | Timestamp fidelity | >=2 / >=3 supported books | Paired completeness | Mapping reliable / ambiguous / missing | Approved |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for key, metrics in report["summary"]["primary_fbs_vs_fbs_by_horizon_market"].items():
        horizon, market = key.split("|")
        lines.append(
            f"| {horizon} | {market} | {metrics['games_requested']} | "
            f"{metrics['games_with_usable_market_snapshot']} | {metrics['coverage_pct']:.2f}% | "
            f"{metrics['median_timestamp_distance_seconds']}s / {metrics['p90_timestamp_distance_seconds']}s | "
            f"{metrics['timestamp_fidelity_pct']:.2f}% | "
            f"{metrics['pct_with_at_least_2_supported_books']:.2f}% / "
            f"{metrics['pct_with_at_least_3_supported_books']:.2f}% | "
            f"{metrics['paired_side_completeness_pct']:.2f}% | "
            f"{metrics['reliable_event_mappings']} / {metrics['ambiguous_event_mappings']} / "
            f"{metrics['missing_event_mappings']} | "
            f"{'yes' if report['approved_horizon_markets'].get(key) else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Supported sportsbook continuity",
            "",
            "| Horizon | Market | DraftKings | FanDuel | BetMGM |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for key, metrics in report["summary"]["primary_fbs_vs_fbs_by_horizon_market"].items():
        horizon, market = key.split("|")
        frequency = metrics["complete_book_frequency"]
        requested = metrics["games_requested"]
        lines.append(
            f"| {horizon} | {market} | {_pct(frequency.get('draftkings', 0), requested):.2f}% | "
            f"{_pct(frequency.get('fanduel', 0), requested):.2f}% | "
            f"{_pct(frequency.get('betmgm', 0), requested):.2f}% |"
        )
    lines.extend(
        [
            "",
            "## Primary FBS-vs-FBS season breakdown",
            "",
            "| Season | Horizon | Market | Games | Coverage | >=2 books | Paired completeness | Unusable reasons |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for key, metrics in report["summary"]["primary_fbs_vs_fbs_by_season_horizon_market"].items():
        season, horizon, market = key.split("|")
        reasons = ", ".join(f"{name}={count}" for name, count in metrics["unusable_reasons"].items()) or "none"
        lines.append(
            f"| {season} | {horizon} | {market} | {metrics['games_requested']} | "
            f"{metrics['coverage_pct']:.2f}% | {metrics['pct_with_at_least_2_supported_books']:.2f}% | "
            f"{metrics['paired_side_completeness_pct']:.2f}% | {reasons} |"
        )
    stable = sum(bool(item["stable"]) for item in report["event_id_stability"].values())
    total_stability = len(report["event_id_stability"])
    lines.extend(
        [
            "",
            "## Timestamp and identity findings",
            "",
            f"The four boundary probes returned closest-prior snapshots as recorded in the machine report. "
            f"Provider event IDs were stable for `{stable}/{total_stability}` matched audited games across horizons.",
            "",
            "| Probe | Requested | Returned | Absolute distance | At/before cutoff |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for probe in report["boundary_probes"]:
        lines.append(
            f"| {probe['request_id']} | {probe['requested_at']} | {probe['returned_snapshot_at']} | "
            f"{probe['distance_seconds']}s | {'yes' if probe['at_or_before'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "Historical archive rows use provider snapshot time for research availability and retain real local "
            "retrieval time. They are not mislabeled as contemporaneous Phase 3 ingestions.",
            "",
            "The approval gates use only the frozen FBS-vs-FBS model cohort. FBS/FCS and other context rows are "
            "retained in the machine-readable cohort/slate summaries and were not silently discarded.",
            "",
            "## Decision",
            "",
            f"**{decision['status']}**. Approved horizon/market combinations: "
            f"`{', '.join(decision['approved_horizon_markets']) or 'none'}`.",
            "",
            f"Recommended game-day-morning convention: "
            f"`{report['morning_recommendation']['recommended_policy']}`.",
            f"The candidates used the same timestamp on "
            f"`{report['morning_recommendation']['slates_with_identical_candidate_timestamp']}/"
            f"{report['morning_recommendation']['slates_compared']}` slates and tied on aggregate coverage. "
            f"{report['morning_recommendation']['recommendation_reason']}",
            "",
            f"A larger bounded historical acquisition is "
            f"{'justified only for the approved combinations' if decision['larger_purchase_justified'] else 'not justified'}.",
            "Do not substitute a missing horizon, loosen the two-book gate, or infer edge from this audit.",
            "",
            "## Limitations",
            "",
            "- This bounded sample covers nine representative slates, not every game or bookmaker vintage.",
            "- Historical snapshots can contain provider corrections and only include books/markets available at that time.",
            "- Display-name reconciliation is deterministic and orientation-aware; missing matches remain missing rather than fuzzy-merged.",
            "- Near-close is a five-minute proxy, not a universal sportsbook-specific closing definition.",
            "- The audit evaluates acquisition feasibility only. It does not compare models, calculate EV, or claim profitability.",
            "",
            "Machine-readable aggregate: [`reports/NCAAF_HISTORICAL_ODDS_AUDIT_2020_2024.json`](reports/NCAAF_HISTORICAL_ODDS_AUDIT_2020_2024.json).",
            "",
        ]
    )
    return "\n".join(lines)
