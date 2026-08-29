from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from app.domain.ncaaf import LOCKED_HOLDOUT_SEASON, validate_development_seasons

NORMALIZED_SCHEMA_VERSION = "ncaaf-normalized-facts-v1"
NORMALIZATION_VERSION = "ncaaf-normalize-cfbd-v1"
AVAILABILITY_POLICY_VERSION = "cfbd-reconstructed-kickoff-plus-24h-v1"
FEATURE_SET_VERSION = "ncaaf-efficiency-point-in-time-v1"
DATASET_SCHEMA_VERSION = "ncaaf-feature-dataset-v1"
FOLD_POLICY_VERSION = "ncaaf-expanding-folds-v1"
OPPONENT_ADJUSTMENT_VERSION = "prior-only-opponent-residual-v1"
EARLY_SEASON_PRIOR_VERSION = "program-shrinkage-k3-v1"
PBP_RECONCILIATION_VERSION = "cfbd-cfbfastr-pbp-reconciliation-v1"

RECONSTRUCTED_DELAY = timedelta(hours=24)
MORNING_TIMEZONE = ZoneInfo("America/New_York")


class PredictionHorizon(StrEnum):
    GAME_DAY_MORNING = "game_day_morning"
    HOURS_24 = "24_hours_before_kickoff"
    MINUTES_60 = "60_minutes_before_kickoff"


class MorningPolicy(StrEnum):
    FIXED_0900_ET_CANDIDATE = "fixed_0900_et_candidate_v1"
    FIRST_KICKOFF_MINUS_3H_CANDIDATE = "first_kickoff_minus_3h_candidate_v1"


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    description: str
    formula: str
    required_sources: tuple[str, ...]
    direction: str
    minimum_sample: int
    missingness: str
    point_in_time_rule: str
    transformation_version: str = FEATURE_SET_VERSION


@dataclass(frozen=True, slots=True)
class FoldDefinition:
    name: str
    role: str
    train_seasons: tuple[int, ...]
    evaluation_season: int
    policy_version: str = FOLD_POLICY_VERSION


def stable_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value)).hexdigest()


def feature_set_hash(definitions: Sequence[FeatureDefinition]) -> str:
    return stable_hash([asdict(item) for item in sorted(definitions, key=lambda item: item.name)])


def reconstructed_available_at(kickoff: datetime) -> datetime:
    if kickoff.tzinfo is None:
        raise ValueError("kickoff must be timezone-aware")
    return kickoff.astimezone(UTC) + RECONSTRUCTED_DELAY


def is_available(
    *,
    effective_at: datetime,
    available_at: datetime,
    as_of: datetime,
) -> bool:
    if any(value.tzinfo is None for value in (effective_at, available_at, as_of)):
        raise ValueError("point-in-time boundaries must be timezone-aware")
    cutoff = as_of.astimezone(UTC)
    return effective_at.astimezone(UTC) <= cutoff and available_at.astimezone(UTC) <= cutoff


def prediction_as_of(
    kickoff: datetime,
    horizon: PredictionHorizon,
    *,
    first_kickoff_of_day: datetime | None = None,
    morning_policy: MorningPolicy = MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
) -> datetime:
    if kickoff.tzinfo is None:
        raise ValueError("kickoff must be timezone-aware")
    kickoff = kickoff.astimezone(UTC)
    if horizon == PredictionHorizon.HOURS_24:
        return kickoff - timedelta(hours=24)
    if horizon == PredictionHorizon.MINUTES_60:
        return kickoff - timedelta(minutes=60)
    if morning_policy == MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE:
        if first_kickoff_of_day is None or first_kickoff_of_day.tzinfo is None:
            raise ValueError("first kickoff is required for the relative morning policy")
        return first_kickoff_of_day.astimezone(UTC) - timedelta(hours=3)
    local_date = kickoff.astimezone(MORNING_TIMEZONE).date()
    fixed = datetime.combine(local_date, datetime.min.time(), MORNING_TIMEZONE).replace(hour=9)
    return fixed.astimezone(UTC)


def validate_feature_seasons(start_season: int, end_season: int, *, allow_holdout: bool = False) -> None:
    validate_development_seasons(start_season, end_season, allow_holdout=allow_holdout)
    if end_season >= LOCKED_HOLDOUT_SEASON and not allow_holdout:
        raise ValueError("locked holdout cannot enter an ordinary feature build")


def chronological_folds() -> tuple[FoldDefinition, ...]:
    return tuple(
        FoldDefinition(
            name=f"develop_through_{season - 1}_evaluate_{season}",
            role="validation" if season == 2024 else "development",
            train_seasons=tuple(range(2014, season)),
            evaluation_season=season,
        )
        for season in range(2019, 2025)
    )


def fold_role(season: int) -> str:
    if season <= 2018:
        return "warmup"
    if season <= 2023:
        return "development"
    if season == 2024:
        return "validation"
    if season == 2025:
        return "locked_test"
    return "prospective_shadow"


def source_manifest_fingerprint(manifests: Sequence[Mapping[str, Any]]) -> str:
    safe = [
        {
            "id": str(item["id"]),
            "endpoint": item["endpoint"],
            "request_hash": item["request_hash"],
            "content_hash": item["content_hash"],
            "schema_version": item["schema_version"],
        }
        for item in manifests
    ]
    return stable_hash(sorted(safe, key=lambda item: (item["endpoint"], item["request_hash"], item["content_hash"])))
