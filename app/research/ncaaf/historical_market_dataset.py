from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from app.providers.odds_api_historical import HistoricalOddsClient, iso_z, parse_iso_timestamp
from app.research.ncaaf.artifacts import ResearchArtifactStore, artifact_dict, dataset_hash
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.historical_odds_audit import (
    AVAILABILITY_POLICY_VERSION,
    CachedResponse,
    HistoricalAuditStore,
    TOLERANCES,
    name_is_compatible,
    reconcile_event,
    timestamp_distance_seconds,
    timestamp_is_eligible,
)

DATASET_VERSION = "ncaaf-historical-market-dataset-v1"
SCHEMA_VERSION = "market-v1"
TRANSFORMATION_VERSION = "ncaaf-historical-market-normalize-v1"
SAMPLING_VERSION = "ncaaf-later-horizon-stratified-v1"
REPORT_VERSION = "ncaaf-historical-market-dataset-report-v1"
EASTERN = ZoneInfo("America/New_York")
FULL_MARKETS = ("h2h", "spreads", "totals")
CLOSE_MARKETS = ("spreads", "totals")
SUPPORTED_BOOKS = frozenset({"draftkings", "fanduel", "betmgm"})
SEASONS = tuple(range(2020, 2025))
MORNING_NEW_CREDIT_LIMIT = 10_290
LATER_NEW_CREDIT_LIMIT = 2_700
LATER_NEW_CALL_LIMIT = 90
MINIMUM_REMAINING_CREDITS = 5_000

UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")
OBSERVATION_SCHEMA = pa.schema(
    [
        ("canonical_event_id", pa.string()),
        ("provider_event_id", pa.string()),
        ("cfbd_game_id", pa.int64()),
        ("season", pa.int16()),
        ("week", pa.int16()),
        ("season_type", pa.string()),
        ("home_program_id", pa.string()),
        ("away_program_id", pa.string()),
        ("home_team", pa.string()),
        ("away_team", pa.string()),
        ("scheduled_kickoff", UTC_TIMESTAMP),
        ("horizon", pa.string()),
        ("requested_at", UTC_TIMESTAMP),
        ("snapshot_at", UTC_TIMESTAMP),
        ("snapshot_distance_seconds", pa.int32()),
        ("sportsbook", pa.string()),
        ("sportsbook_name", pa.string()),
        ("supported_sportsbook", pa.bool_()),
        ("market_type", pa.string()),
        ("side", pa.string()),
        ("point", pa.float64()),
        ("american_odds", pa.int32()),
        ("decimal_odds", pa.string()),
        ("implied_probability", pa.string()),
        ("source_request_hash", pa.string()),
        ("source_content_hash", pa.string()),
        ("source_manifest_uri", pa.string()),
        ("availability_policy_version", pa.string()),
    ]
)
GROUP_SCHEMA = pa.schema(
    [
        ("canonical_event_id", pa.string()),
        ("cfbd_game_id", pa.int64()),
        ("season", pa.int16()),
        ("week", pa.int16()),
        ("horizon", pa.string()),
        ("market_type", pa.string()),
        ("requested_at", UTC_TIMESTAMP),
        ("snapshot_at", UTC_TIMESTAMP),
        ("mapping_status", pa.string()),
        ("complete_supported_books", pa.int16()),
        ("complete_all_books", pa.int16()),
        ("usable", pa.bool_()),
        ("unusable_reasons", pa.string()),
    ]
)


@dataclass(frozen=True, slots=True)
class MarketGame:
    provider_game_id: int
    canonical_event_id: str
    season: int
    week: int | None
    season_type: str
    kickoff: datetime
    home_program_id: str
    away_program_id: str
    home_team: str
    away_team: str
    home_classification: str
    away_classification: str
    model_eligible: bool


@dataclass(frozen=True, slots=True)
class MarketRequest:
    request_id: str
    acquisition: str
    horizon: str
    requested_at: datetime
    markets: tuple[str, ...]
    intended_game_ids: tuple[int, ...]
    strata: tuple[str, ...] = ()
    collection_version: str = DATASET_VERSION

    @property
    def safe_parameters(self) -> dict[str, Any]:
        return {
            "sport": "americanfootball_ncaaf",
            "regions": "us",
            "markets": list(self.markets),
            "odds_format": "american",
            "date_format": "iso",
            "date": iso_z(self.requested_at),
        }

    @property
    def request_hash(self) -> str:
        return stable_hash({"provider": "the_odds_api", "endpoint": "historical_odds", **self.safe_parameters})

    @property
    def credit_cost(self) -> int:
        return len(self.markets) * 10


class HistoricalMarketCache:
    """Exact or market-superset lookup over the immutable Phase 5B-7A archive."""

    def __init__(self, root: Path) -> None:
        self.store = HistoricalAuditStore(root)
        self._by_timestamp: dict[datetime, list[tuple[frozenset[str], Path, dict[str, Any]]]] = defaultdict(list)
        for path in self.store.root.joinpath("m").rglob("*.json"):
            manifest = dict(json.loads(path.read_text(encoding="utf-8")))
            timestamp = parse_iso_timestamp(manifest.get("requested_snapshot_at"))
            markets = frozenset(manifest.get("request_parameters", {}).get("markets", []))
            if timestamp is not None and markets:
                self._by_timestamp[timestamp].append((markets, path, manifest))

    def find(self, request: MarketRequest) -> CachedResponse | None:
        exact = self.store.load(request)
        if exact is not None:
            return exact
        needed = frozenset(request.markets)
        candidates = [item for item in self._by_timestamp.get(request.requested_at, []) if item[0] >= needed]
        if not candidates:
            return None
        _, manifest_path, manifest = min(candidates, key=lambda item: (len(item[0]), str(item[1])))
        artifact = (self.store.root / str(manifest["artifact_uri"])).resolve()
        if not artifact.is_relative_to(self.store.root):
            raise ValueError("historical cache artifact escapes root")
        raw = gzip.decompress(artifact.read_bytes())
        if hashlib.sha256(raw).hexdigest() != manifest["content_hash"]:
            raise ValueError("historical cache content hash mismatch")
        payload = json.loads(raw)
        return CachedResponse(
            request_hash=str(manifest["request_hash"]),
            content_hash=str(manifest["content_hash"]),
            retrieved_at=_timestamp(manifest["retrieved_at"]),
            payload=dict(payload),
            manifest=manifest,
            cache_hit=True,
        )

    def put(self, request: MarketRequest, response: Any) -> CachedResponse:
        cached = self.store.put(request, response)
        manifest_path = next(
            self.store.root.joinpath("m", request.request_hash[:20]).glob(f"{cached.content_hash}.json")
        )
        self._by_timestamp[request.requested_at].append(
            (frozenset(request.markets), manifest_path, cached.manifest)
        )
        return cached


def load_market_games(root: Path, start_season: int = 2020, end_season: int = 2024) -> tuple[MarketGame, ...]:
    if start_season < 2020 or end_season > 2024 or start_season > end_season:
        raise ValueError("historical market development seasons must remain within 2020-2024")
    pointer = json.loads((root / "normalized" / "current.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / pointer["uri"]).read_text(encoding="utf-8"))
    columns = [field.name for field in MarketGame.__dataclass_fields__.values()]
    games: list[MarketGame] = []
    for season in range(start_season, end_season + 1):
        artifact = next(
            item for item in manifest["artifacts"] if item["dataset"] == "games" and item["season"] == season
        )
        rows = pq.ParquetFile(root / artifact["uri"]).read(columns=columns).to_pylist()
        games.extend(MarketGame(**row) for row in rows if row["model_eligible"])
    if any(game.season >= 2025 for game in games):
        raise ValueError("locked 2025 holdout entered historical market plan")
    return tuple(sorted(games, key=lambda item: (item.kickoff, item.provider_game_id)))


def build_morning_plan(games: Sequence[MarketGame]) -> tuple[MarketRequest, ...]:
    by_day: dict[date, list[MarketGame]] = defaultdict(list)
    for game in games:
        by_day[game.kickoff.astimezone(EASTERN).date()].append(game)
    requests = []
    for slate_date, slate_games in sorted(by_day.items()):
        first = min(game.kickoff for game in slate_games)
        requests.append(
            MarketRequest(
                request_id=f"morning-{slate_date.isoformat()}",
                acquisition="primary_complete_morning",
                horizon="morning_first_kickoff_minus_3h",
                requested_at=first - timedelta(hours=3),
                markets=FULL_MARKETS,
                intended_game_ids=tuple(sorted(game.provider_game_id for game in slate_games)),
            )
        )
    return tuple(requests)


def select_later_robustness_games(games: Sequence[MarketGame]) -> tuple[MarketGame, ...]:
    """Two outcome-blind games per season/phase, preferring distinct kickoff windows."""
    by_stratum: dict[tuple[int, str, str], list[MarketGame]] = defaultdict(list)
    for game in games:
        phase = _season_phase(game)
        window = _kickoff_window(game)
        by_stratum[(game.season, phase, window)].append(game)
    selected: list[MarketGame] = []
    for season in SEASONS:
        for phase in ("early_regular", "middle_regular", "late_regular", "postseason"):
            available = {
                window: sorted(
                    by_stratum.get((season, phase, window), []),
                    key=lambda game: stable_hash(
                        {"sampling": SAMPLING_VERSION, "season": season, "phase": phase, "game": game.provider_game_id}
                    ),
                )
                for window in ("early", "middle", "late")
            }
            windows = sorted(
                (window for window, candidates in available.items() if candidates),
                key=lambda window: stable_hash(
                    {"sampling": SAMPLING_VERSION, "season": season, "phase": phase, "window": window}
                ),
            )
            chosen = [available[window][0] for window in windows[:2]]
            if len(chosen) < 2:
                remainder = sorted(
                    (game for candidates in available.values() for game in candidates if game not in chosen),
                    key=lambda game: stable_hash(
                        {"sampling": SAMPLING_VERSION, "season": season, "phase": phase, "game": game.provider_game_id}
                    ),
                )
                chosen.extend(remainder[: 2 - len(chosen)])
            selected.extend(chosen)
    return tuple(sorted({game.provider_game_id: game for game in selected}.values(), key=lambda item: item.provider_game_id))


def build_later_plan(games: Sequence[MarketGame], root: Path) -> tuple[MarketRequest, ...]:
    by_id = {game.provider_game_id: game for game in games}
    selected = {game.provider_game_id: game for game in select_later_robustness_games(games)}
    # Every eligible 7A anchor remains part of the robustness cohort, even when it
    # was not selected by the new deterministic strata.
    from app.research.ncaaf.historical_odds_audit import build_audit_plan, load_audit_games

    if root.joinpath("normalized", "current.json").is_file():
        for request in build_audit_plan(load_audit_games(root)):
            if request.horizon in {"60_minutes_before_kickoff", "near_close_5_minutes"}:
                for game_id in request.intended_game_ids:
                    if game_id in by_id:
                        selected[game_id] = by_id[game_id]
    targets: dict[tuple[str, datetime, tuple[str, ...]], list[MarketGame]] = defaultdict(list)
    for game in selected.values():
        targets[("60_minutes_before_kickoff", game.kickoff - timedelta(minutes=60), FULL_MARKETS)].append(game)
        targets[("near_close_5_minutes", game.kickoff - timedelta(minutes=5), CLOSE_MARKETS)].append(game)
    requests: list[MarketRequest] = []
    for (horizon, requested_at, markets), target_games in sorted(targets.items(), key=lambda item: item[0][1]):
        strata = tuple(sorted({_stratum_label(game) for game in target_games}))
        requests.append(
            MarketRequest(
                request_id=f"robustness-{horizon}-{iso_z(requested_at)}",
                acquisition="secondary_later_horizon_robustness",
                horizon=horizon,
                requested_at=requested_at,
                markets=markets,
                intended_game_ids=tuple(sorted(game.provider_game_id for game in target_games)),
                strata=strata,
            )
        )
    return tuple(requests)


def acquisition_plan_summary(
    requests: Sequence[MarketRequest], cache: HistoricalMarketCache, *, available_credits: int | None
) -> dict[str, Any]:
    cached = [request for request in requests if cache.find(request) is not None]
    missing_by_hash = {
        request.request_hash: request for request in requests if cache.find(request) is None
    }
    credits = sum(request.credit_cost for request in missing_by_hash.values())
    return {
        "dataset_version": DATASET_VERSION,
        "acquisition": requests[0].acquisition if requests else None,
        "logical_requests": len(requests),
        "unique_provider_requests": len(missing_by_hash),
        "cache_hits": len(cached),
        "cost_per_request": dict(
            sorted(Counter(request.credit_cost for request in missing_by_hash.values()).items())
        ),
        "expected_new_credits": credits,
        "available_credits": available_credits,
        "expected_remaining_credits": None if available_credits is None else available_credits - credits,
        "acquisition_plan_hash": stable_hash([request_to_dict(item) for item in requests]),
        "requests": [request_to_dict(item) for item in requests],
    }


def execute_plan(
    requests: Sequence[MarketRequest],
    client: HistoricalOddsClient,
    cache: HistoricalMarketCache,
    *,
    credit_limit: int,
    new_call_limit: int | None = None,
) -> tuple[dict[str, CachedResponse], dict[str, Any]]:
    before = client.usage()
    available = before.get("requests_remaining")
    if not isinstance(available, int):
        raise RuntimeError("provider did not return a numeric remaining-credit balance")
    summary = acquisition_plan_summary(requests, cache, available_credits=available)
    expected = int(summary["expected_new_credits"])
    new_calls = int(summary["unique_provider_requests"])
    if expected > credit_limit:
        raise RuntimeError(f"plan requires {expected} credits, exceeding authorized limit {credit_limit}")
    if available - expected < MINIMUM_REMAINING_CREDITS:
        raise RuntimeError("plan would violate the 5000-credit reserve; no historical request was made")
    if new_call_limit is not None and new_calls > new_call_limit:
        raise RuntimeError(
            f"plan requires {new_calls} new calls, exceeding authorized limit {new_call_limit}"
        )
    responses: dict[str, CachedResponse] = {}
    network_calls = 0
    for request in requests:
        cached = cache.find(request)
        if cached is None:
            response = client.fetch(request.requested_at, markets=request.markets)
            cached = cache.put(request, response)
            network_calls += 1
        _validate_cached_response(request, cached)
        responses[request.request_id] = cached
    after = client.usage()
    consumed = _usage_delta(before, after)
    if consumed is None or consumed > credit_limit:
        raise RuntimeError("provider credit accounting is unavailable or exceeded the authorized limit")
    return responses, {
        **summary,
        "network_calls": network_calls,
        "credits_consumed": consumed,
        "usage_before": before,
        "usage_after": after,
    }


def validate_cached_plan(
    requests: Sequence[MarketRequest], cache: HistoricalMarketCache
) -> list[str]:
    """Validate completeness and closest-prior integrity before a later phase proceeds."""
    errors: list[str] = []
    for request in requests:
        cached = cache.find(request)
        if cached is None:
            errors.append(f"missing cached historical request {request.request_id}")
            continue
        try:
            _validate_cached_response(request, cached)
        except ValueError as exc:
            errors.append(f"{request.request_id}: {exc}")
    return errors


def load_cached_responses(
    requests: Sequence[MarketRequest], cache: HistoricalMarketCache
) -> dict[str, CachedResponse]:
    responses: dict[str, CachedResponse] = {}
    for request in requests:
        cached = cache.find(request)
        if cached is None:
            raise FileNotFoundError(f"missing cached historical request {request.request_id}")
        responses[request.request_id] = cached
    return responses


def build_historical_market_dataset(
    root: Path,
    games: Sequence[MarketGame],
    requests: Sequence[MarketRequest],
    responses: Mapping[str, CachedResponse],
    *,
    acquisition_plan_hashes: Sequence[str],
) -> dict[str, Any]:
    by_id = {game.provider_game_id: game for game in games}
    observations_by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    groups_by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    source_manifests: dict[tuple[str, str], dict[str, Any]] = {}
    for request in requests:
        cached = responses[request.request_id]
        manifest_uri = _manifest_uri(cached)
        source_manifests[(cached.request_hash, cached.content_hash)] = {
            "id": cached.request_hash,
            "content_hash": cached.content_hash,
        }
        returned = parse_iso_timestamp(cached.payload.get("timestamp"))
        fidelity = timestamp_is_eligible(request.requested_at, returned)
        raw_events = [item for item in cached.payload.get("data", []) if isinstance(item, dict)]
        for game_id in request.intended_game_ids:
            game = by_id[game_id]
            mapping_status, event = reconcile_event(_audit_game(game), raw_events)
            for market in request.markets:
                rows, complete_supported, complete_all = _normalize_market(
                    game, event, market, request, cached, returned, manifest_uri
                )
                reasons: list[str] = []
                if mapping_status != "reliable":
                    reasons.append(f"event_mapping_{mapping_status}")
                if not fidelity:
                    reasons.append("snapshot_not_closest_prior_within_tolerance")
                if complete_supported < TOLERANCES.minimum_supported_complete_books:
                    reasons.append("insufficient_supported_complete_books")
                observations_by_season[game.season].extend(rows)
                groups_by_season[game.season].append(
                    {
                        "canonical_event_id": game.canonical_event_id,
                        "cfbd_game_id": game.provider_game_id,
                        "season": game.season,
                        "week": game.week,
                        "horizon": request.horizon,
                        "market_type": market,
                        "requested_at": request.requested_at,
                        "snapshot_at": returned,
                        "mapping_status": mapping_status,
                        "complete_supported_books": complete_supported,
                        "complete_all_books": complete_all,
                        "usable": not reasons,
                        "unusable_reasons": "|".join(reasons),
                    }
                )
    store = ResearchArtifactStore(root)
    artifacts: list[dict[str, Any]] = []
    safe_sources = list(source_manifests.values())
    for season in SEASONS:
        observation_table = pa.Table.from_pylist(observations_by_season[season], schema=OBSERVATION_SCHEMA)
        group_table = pa.Table.from_pylist(groups_by_season[season], schema=GROUP_SCHEMA)
        observations = store.write_parquet(
            observation_table,
            namespace="historical-market",
            dataset="observations",
            season=season,
            schema_version=SCHEMA_VERSION,
            transformation_version=TRANSFORMATION_VERSION,
            source_manifests=safe_sources,
            sort_by=(("scheduled_kickoff", "ascending"), ("horizon", "ascending"), ("market_type", "ascending"), ("sportsbook", "ascending"), ("side", "ascending")),
        )
        groups = store.write_parquet(
            group_table,
            namespace="historical-market",
            dataset="groups",
            season=season,
            schema_version=SCHEMA_VERSION,
            transformation_version=TRANSFORMATION_VERSION,
            source_manifests=safe_sources,
            sort_by=(("cfbd_game_id", "ascending"), ("horizon", "ascending"), ("market_type", "ascending")),
        )
        artifacts.extend((artifact_dict(observations), artifact_dict(groups)))
    configuration = {
        "dataset_version": DATASET_VERSION,
        "schema_version": SCHEMA_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "availability_policy_version": AVAILABILITY_POLICY_VERSION,
        "season_range": [2020, 2024],
        "approved_horizons": ["morning_first_kickoff_minus_3h", "60_minutes_before_kickoff", "near_close_5_minutes"],
        "approved_markets_by_horizon": {
            "morning_first_kickoff_minus_3h": list(FULL_MARKETS),
            "60_minutes_before_kickoff": list(FULL_MARKETS),
            "near_close_5_minutes": list(CLOSE_MARKETS),
        },
        "evidence_role_by_horizon": {
            "morning_first_kickoff_minus_3h": "primary_complete_cohort",
            "60_minutes_before_kickoff": "secondary_robustness_sample",
            "near_close_5_minutes": "secondary_robustness_sample",
        },
        "later_sampling_version": SAMPLING_VERSION,
        "supported_books": sorted(SUPPORTED_BOOKS),
        "acquisition_plan_hashes": sorted(acquisition_plan_hashes),
        "source_manifest_hash": stable_hash(safe_sources),
    }
    result = {
        **configuration,
        "artifacts": artifacts,
        "row_count": sum(item["row_count"] for item in artifacts if item["dataset"] == "observations"),
        "group_count": sum(item["row_count"] for item in artifacts if item["dataset"] == "groups"),
        "event_count": len({row["canonical_event_id"] for values in groups_by_season.values() for row in values}),
        "schema_hash": hashlib.sha256(OBSERVATION_SCHEMA.serialize().to_pybytes()).hexdigest(),
    }
    result["dataset_hash"] = dataset_hash(artifacts, configuration)
    manifest_id, _ = store.write_manifest("historical-market", result)
    return store.load_manifest("historical-market", manifest_id)


def validate_historical_market_dataset(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    store = ResearchArtifactStore(root)
    if manifest.get("season_range") != [2020, 2024]:
        errors.append("historical market season range is not 2020-2024")
    configuration_keys = (
        "dataset_version",
        "schema_version",
        "transformation_version",
        "availability_policy_version",
        "season_range",
        "approved_horizons",
        "approved_markets_by_horizon",
        "evidence_role_by_horizon",
        "later_sampling_version",
        "supported_books",
        "acquisition_plan_hashes",
        "source_manifest_hash",
    )
    configuration = {key: manifest.get(key) for key in configuration_keys}
    expected_hash = dataset_hash(manifest.get("artifacts", []), configuration)
    if manifest.get("dataset_hash") != expected_hash:
        errors.append("historical market dataset hash mismatch")
    for artifact in manifest.get("artifacts", []):
        errors.extend(store.validate_artifact(artifact))
        table = store.read_table(str(artifact["uri"]))
        if "requested_at" in table.column_names and "snapshot_at" in table.column_names:
            for requested, snapshot in zip(table["requested_at"].to_pylist(), table["snapshot_at"].to_pylist(), strict=True):
                if snapshot is not None and snapshot > requested:
                    errors.append(f"future snapshot in {artifact['uri']}")
                    break
    return errors


def summarize_dataset(root: Path, manifest: Mapping[str, Any], executions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    store = ResearchArtifactStore(root)
    groups = pa.concat_tables(
        [store.read_table(str(item["uri"])) for item in manifest["artifacts"] if item["dataset"] == "groups"]
    ).to_pylist()
    observations = pa.concat_tables(
        [store.read_table(str(item["uri"])) for item in manifest["artifacts"] if item["dataset"] == "observations"]
    ).to_pylist()
    by_key: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    reasons: Counter[str] = Counter()
    for group in groups:
        by_key[(int(group["season"]), str(group["horizon"]), str(group["market_type"]))].append(group)
        reasons.update(item for item in str(group["unusable_reasons"]).split("|") if item)
    coverage = {}
    for key, values in sorted(by_key.items()):
        usable = sum(bool(item["usable"]) for item in values)
        coverage["|".join(map(str, key))] = {
            "games": len(values),
            "usable": usable,
            "coverage_pct": _pct(usable, len(values)),
            "at_least_2_books_pct": _pct(sum(int(item["complete_supported_books"]) >= 2 for item in values), len(values)),
            "at_least_3_books_pct": _pct(sum(int(item["complete_supported_books"]) >= 3 for item in values), len(values)),
            "reliable_mappings": sum(item["mapping_status"] == "reliable" for item in values),
            "ambiguous_mappings": sum(item["mapping_status"] == "ambiguous" for item in values),
            "missing_mappings": sum(item["mapping_status"] == "missing" for item in values),
        }
    snapshot_pairs = {
        (item["requested_at"], item["snapshot_at"])
        for item in groups
        if item["snapshot_at"] is not None
    }
    distances = sorted(
        int((requested - snapshot).total_seconds()) for requested, snapshot in snapshot_pairs
    )
    books = Counter(str(item["sportsbook"]) for item in observations)
    games_by_season: dict[str, set[str]] = defaultdict(set)
    mapped_by_season: dict[str, set[str]] = defaultdict(set)
    mappings: dict[tuple[str, str], str] = {}
    rows_by_market: Counter[str] = Counter()
    for group in groups:
        season = str(group["season"])
        event_id = str(group["canonical_event_id"])
        games_by_season[season].add(event_id)
        mappings[(event_id, str(group["horizon"]))] = str(group["mapping_status"])
        if group["mapping_status"] == "reliable":
            mapped_by_season[season].add(event_id)
    for item in observations:
        rows_by_market[
            f"{item['horizon']}|{item['market_type']}|{item['sportsbook']}"
        ] += 1
    mapping_counts = Counter(mappings.values())
    aggregate_coverage: dict[str, dict[str, Any]] = {}
    aggregate_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        aggregate_groups[(str(group["horizon"]), str(group["market_type"]))].append(group)
    for (horizon, market), values in sorted(aggregate_groups.items()):
        usable = sum(bool(item["usable"]) for item in values)
        aggregate_coverage[f"{horizon}|{market}"] = {
            "games": len(values),
            "usable": usable,
            "coverage_pct": _pct(usable, len(values)),
            "at_least_2_books_pct": _pct(
                sum(int(item["complete_supported_books"]) >= 2 for item in values), len(values)
            ),
            "at_least_3_books_pct": _pct(
                sum(int(item["complete_supported_books"]) >= 3 for item in values), len(values)
            ),
        }
    return {
        "report_version": REPORT_VERSION,
        "dataset_version": DATASET_VERSION,
        "dataset_hash": manifest["dataset_hash"],
        "manifest_id": manifest["manifest_id"],
        "built_at": manifest.get("built_at"),
        "schema_version": manifest["schema_version"],
        "transformation_version": manifest["transformation_version"],
        "availability_policy_version": manifest["availability_policy_version"],
        "acquisition_plan_hashes": manifest["acquisition_plan_hashes"],
        "source_manifest_hash": manifest["source_manifest_hash"],
        "evidence_role_by_horizon": manifest["evidence_role_by_horizon"],
        "row_count": manifest["row_count"],
        "event_count": manifest["event_count"],
        "group_count": manifest["group_count"],
        "coverage": coverage,
        "aggregate_coverage": aggregate_coverage,
        "games_by_season": {
            season: len(values) for season, values in sorted(games_by_season.items())
        },
        "reliably_mapped_games_by_season": {
            season: len(values) for season, values in sorted(mapped_by_season.items())
        },
        "event_horizon_reconciliation": dict(sorted(mapping_counts.items())),
        "rows_by_horizon_market_book": dict(sorted(rows_by_market.items())),
        "timestamp_distance_seconds": {"median": _quantile(distances, 0.5), "p90": _quantile(distances, 0.9)},
        "sportsbook_frequency": dict(sorted(books.items())),
        "unusable_reasons": dict(sorted(reasons.items())),
        "phase_5b_7c_readiness": {
            "status": "GO_MORNING_PRIMARY_WITH_LATER_DIAGNOSTIC_ONLY",
            "morning_primary_unblocked": True,
            "later_full_cohort_available": False,
            "limitations": [
                "60-minute and near-close results are a bounded robustness sample",
                "missing and ambiguous events remain excluded",
                "no consensus, model comparison, edge, EV, or CLV was calculated",
            ],
        },
        "executions": [_execution_summary(item) for item in executions],
        "raw_stored_bytes": sum(path.stat().st_size for path in root.joinpath("odds-audit-v1").rglob("*") if path.is_file()),
        "normalized_stored_bytes": sum(int(item["stored_bytes"]) for item in manifest["artifacts"]),
    }


def _execution_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"requests", "usage_before", "usage_after"}
    }


def request_to_dict(request: MarketRequest) -> dict[str, Any]:
    value = asdict(request)
    value["requested_at"] = iso_z(request.requested_at)
    value["request_hash"] = request.request_hash
    value["credit_cost"] = request.credit_cost
    return value


def _normalize_market(
    game: MarketGame,
    event: Mapping[str, Any] | None,
    market_key: str,
    request: MarketRequest,
    cached: CachedResponse,
    returned: datetime | None,
    manifest_uri: str,
) -> tuple[list[dict[str, Any]], int, int]:
    if event is None:
        return [], 0, 0
    rows: list[dict[str, Any]] = []
    complete_supported = 0
    complete_all = 0
    for book in event.get("bookmakers", []):
        if not isinstance(book, dict) or not isinstance(book.get("key"), str):
            continue
        market = next((item for item in book.get("markets", []) if isinstance(item, dict) and item.get("key") == market_key), None)
        if market is None:
            continue
        outcomes = [item for item in market.get("outcomes", []) if isinstance(item, dict)]
        normalized = _normalize_outcomes(game, market_key, outcomes)
        if normalized is None:
            continue
        complete_all += 1
        supported = str(book["key"]) in SUPPORTED_BOOKS
        if supported:
            complete_supported += 1
        for item in normalized:
            rows.append(
                {
                    "canonical_event_id": game.canonical_event_id,
                    "provider_event_id": str(event.get("id")),
                    "cfbd_game_id": game.provider_game_id,
                    "season": game.season,
                    "week": game.week,
                    "season_type": game.season_type,
                    "home_program_id": game.home_program_id,
                    "away_program_id": game.away_program_id,
                    "home_team": game.home_team,
                    "away_team": game.away_team,
                    "scheduled_kickoff": game.kickoff,
                    "horizon": request.horizon,
                    "requested_at": request.requested_at,
                    "snapshot_at": returned,
                    "snapshot_distance_seconds": timestamp_distance_seconds(request.requested_at, returned),
                    "sportsbook": str(book["key"]),
                    "sportsbook_name": str(book.get("title") or book["key"]),
                    "supported_sportsbook": supported,
                    "market_type": market_key,
                    **item,
                    "source_request_hash": cached.request_hash,
                    "source_content_hash": cached.content_hash,
                    "source_manifest_uri": manifest_uri,
                    "availability_policy_version": AVAILABILITY_POLICY_VERSION,
                }
            )
    return rows, complete_supported, complete_all


def _normalize_outcomes(
    game: MarketGame, market: str, outcomes: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]] | None:
    if len(outcomes) != 2:
        return None
    rows = []
    for outcome in outcomes:
        price = _american(outcome.get("price"))
        if price is None:
            return None
        name = str(outcome.get("name", ""))
        if market in {"h2h", "spreads"}:
            if name_is_compatible(name, game.home_team):
                side = "home"
            elif name_is_compatible(name, game.away_team):
                side = "away"
            else:
                return None
        else:
            side = name.casefold()
            if side not in {"over", "under"}:
                return None
        point = _finite(outcome.get("point")) if market != "h2h" else None
        decimal = _american_to_decimal(price)
        rows.append(
            {
                "side": side,
                "point": point,
                "american_odds": price,
                "decimal_odds": format(decimal, "f"),
                "implied_probability": format(Decimal(1) / decimal, "f"),
            }
        )
    if {item["side"] for item in rows} != ({"home", "away"} if market != "totals" else {"over", "under"}):
        return None
    if market == "spreads" and (
        rows[0]["point"] is None or rows[1]["point"] is None or not math.isclose(float(rows[0]["point"]) + float(rows[1]["point"]), 0, abs_tol=1e-9)
    ):
        return None
    if market == "totals" and (
        rows[0]["point"] is None or rows[1]["point"] is None or not math.isclose(float(rows[0]["point"]), float(rows[1]["point"]), abs_tol=1e-9)
    ):
        return None
    return rows


def _season_phase(game: MarketGame) -> str:
    if game.season_type.casefold() != "regular":
        return "postseason"
    week = game.week or 0
    if week <= 4:
        return "early_regular"
    if week <= 9:
        return "middle_regular"
    return "late_regular"


def _kickoff_window(game: MarketGame) -> str:
    hour = game.kickoff.astimezone(EASTERN).hour
    if hour < 15:
        return "early"
    if hour < 19:
        return "middle"
    return "late"


def _stratum_label(game: MarketGame) -> str:
    return f"{game.season}|{_season_phase(game)}|{_kickoff_window(game)}"


def _audit_game(game: MarketGame) -> Any:
    from app.research.ncaaf.historical_odds_audit import AuditGame

    return AuditGame(
        provider_game_id=game.provider_game_id,
        canonical_event_id=game.canonical_event_id,
        season=game.season,
        week=game.week,
        season_type=game.season_type,
        kickoff=game.kickoff,
        home_team=game.home_team,
        away_team=game.away_team,
        home_classification=game.home_classification,
        away_classification=game.away_classification,
        home_conference=None,
        away_conference=None,
        model_eligible=game.model_eligible,
    )


def _manifest_uri(cached: CachedResponse) -> str:
    return f"m/{cached.request_hash[:20]}/{cached.content_hash}.json"


def _american(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if abs(result) >= 100 else None


def _american_to_decimal(odds: int) -> Decimal:
    value = Decimal(odds)
    return Decimal(1) + (value / Decimal(100) if odds > 0 else Decimal(100) / abs(value))


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any) -> datetime:
    parsed = parse_iso_timestamp(value)
    if parsed is None:
        raise ValueError("invalid historical timestamp")
    return parsed


def _usage_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> int | None:
    left, right = before.get("requests_used"), after.get("requests_used")
    return right - left if isinstance(left, int) and isinstance(right, int) else None


def _validate_cached_response(request: MarketRequest, cached: CachedResponse) -> None:
    returned = parse_iso_timestamp(cached.payload.get("timestamp"))
    if returned is None:
        raise ValueError("provider response has no valid snapshot timestamp")
    if returned > request.requested_at:
        raise ValueError("provider returned a future snapshot")
    if not timestamp_is_eligible(request.requested_at, returned):
        raise ValueError("provider snapshot is outside the approved closest-prior tolerance")


def _pct(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 4) if denominator else 0.0


def _quantile(values: Sequence[int], fraction: float) -> int | None:
    if not values:
        return None
    if fraction == 0.5:
        return int(median(values))
    return values[min(len(values) - 1, math.ceil(fraction * len(values)) - 1)]
