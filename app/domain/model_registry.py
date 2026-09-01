from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID

NCAAF_V1_VERSION = "ncaaf-fair-value-v1"
NCAAF_MORNING_HORIZON = "morning_first_kickoff_minus_3h"
REGISTRY_VERSION = "ncaaf-model-registry-v1"
SHADOW_SCHEMA_VERSION = "ncaaf-shadow-prediction-v1"
OUTCOME_SCHEMA_VERSION = "ncaaf-shadow-outcome-v1"


class ModelStatus(StrEnum):
    RETAINED_BENCHMARK = "retained_benchmark"
    SHADOW_CANDIDATE = "shadow_candidate"
    DIAGNOSTIC = "diagnostic"
    REJECTED = "rejected"
    RETIRED = "retired"


class RegistryError(ValueError):
    pass


class RegistryConflictError(RegistryError):
    pass


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise RegistryError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _probability(value: Decimal | None, name: str, *, required: bool = True) -> Decimal | None:
    if value is None:
        if required:
            raise RegistryError(f"{name} is required")
        return None
    if not value.is_finite() or value < 0 or value > 1:
        raise RegistryError(f"{name} must be finite and between 0 and 1")
    return value


@dataclass(frozen=True, slots=True)
class ModelRegistration:
    model_id: str
    league: str
    market_type: str
    version: str
    status: ModelStatus
    model_family: str
    feature_set_hash: str | None
    source_dataset_hashes: Mapping[str, str]
    research_run_hashes: Mapping[str, str]
    calibration_version: str | None
    consensus_version: str | None
    vig_removal_version: str | None
    holdout_result: str | None
    promotion_decision: str
    artifact_locations: tuple[Mapping[str, str], ...]
    code_build_version: str

    def __post_init__(self) -> None:
        if not all((self.model_id, self.league, self.market_type, self.version, self.model_family)):
            raise RegistryError("model registration identity fields are required")
        if self.status == ModelStatus.REJECTED and "reject" not in self.promotion_decision.lower():
            raise RegistryError("rejected models require an explicit rejected promotion decision")

    @property
    def entry_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class ArtifactRegistration:
    artifact_id: str
    artifact_type: str
    version: str
    status: str
    content_hash: str
    source_hashes: Mapping[str, str]
    locations: tuple[Mapping[str, str], ...]
    code_build_version: str
    metadata: Mapping[str, Any]

    @property
    def entry_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class ConsensusFairValueInput:
    canonical_event_id: UUID
    market_type: str
    selection_side: str
    fair_probability: Decimal | None
    fair_point: Decimal | None
    push_probability: Decimal | None
    as_of: datetime
    source_books: tuple[str, ...]
    consensus_dispersion: Decimal | None
    quality_metadata: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.market_type not in {"moneyline", "spread", "total"}:
            raise RegistryError("unsupported fair-value market type")
        allowed = {"moneyline": {"home", "away"}, "spread": {"home", "away"}, "total": {"over", "under"}}
        if self.selection_side not in allowed[self.market_type]:
            raise RegistryError("selection side does not match market type")
        _probability(self.fair_probability, "fair_probability")
        _probability(self.push_probability, "push_probability", required=self.market_type != "moneyline")
        if self.market_type != "moneyline" and self.fair_point is None:
            raise RegistryError("spread and total fair values require an exact point")
        if self.fair_point is not None and not self.fair_point.is_finite():
            raise RegistryError("fair_point must be finite")
        if (
            self.market_type in {"spread", "total"}
            and self.fair_point is not None
            and self.fair_point == self.fair_point.to_integral_value()
            and self.push_probability == 0
        ):
            raise RegistryError("integer lines require an explicit nonzero push model")
        if self.consensus_dispersion is not None and (
            not self.consensus_dispersion.is_finite() or self.consensus_dispersion < 0
        ):
            raise RegistryError("consensus_dispersion must be finite and nonnegative")
        if len(set(self.source_books)) < 2:
            raise RegistryError("retained consensus requires at least two source books")
        _utc(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class FairValueQuote:
    canonical_event_id: UUID
    model_id: str
    model_version: str
    model_status: ModelStatus
    market_type: str
    selection_side: str
    fair_probability: Decimal | None
    fair_point: Decimal | None
    push_probability: Decimal | None
    uncertainty_quality: Mapping[str, Any]
    source_as_of: datetime
    source_books: tuple[str, ...]
    source_book_count: int
    consensus_dispersion: Decimal | None
    provenance: Mapping[str, Any]
    interface_version: str = NCAAF_V1_VERSION

    @property
    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fair_value_hash(self) -> str:
        return canonical_hash(self.payload)


@dataclass(frozen=True, slots=True)
class ShadowPredictionDraft:
    fair_value: FairValueQuote
    season: int
    week: int | None
    prediction_timestamp: datetime
    intended_horizon: str

    def __post_init__(self) -> None:
        if self.season < 2026:
            raise RegistryError("shadow predictions are prospective beginning with 2026")
        _utc(self.prediction_timestamp, "prediction_timestamp")
        if self.intended_horizon != NCAAF_MORNING_HORIZON:
            raise RegistryError("NCAAF v1 shadow predictions require the frozen morning horizon")
        if self.prediction_timestamp != self.fair_value.source_as_of:
            raise RegistryError("prediction timestamp must equal the fair-value source as-of")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": SHADOW_SCHEMA_VERSION,
            "fair_value": self.fair_value.payload,
            "season": self.season,
            "week": self.week,
            "prediction_timestamp": self.prediction_timestamp,
            "intended_horizon": self.intended_horizon,
        }

    @property
    def prediction_hash(self) -> str:
        return canonical_hash(self.payload)

    @property
    def prediction_id(self) -> str:
        return f"ncaaf-shadow-{self.prediction_hash[:32]}"


@dataclass(frozen=True, slots=True)
class ShadowOutcomeDraft:
    prediction_id: str
    final_home_score: int
    final_away_score: int
    source: str
    final_at: datetime

    def __post_init__(self) -> None:
        if self.final_home_score < 0 or self.final_away_score < 0:
            raise RegistryError("final scores must be nonnegative")
        if not self.source:
            raise RegistryError("outcome source is required")
        _utc(self.final_at, "final_at")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": OUTCOME_SCHEMA_VERSION,
            "prediction_id": self.prediction_id,
            "final_home_score": self.final_home_score,
            "final_away_score": self.final_away_score,
            "source": self.source,
            "final_at": self.final_at,
        }

    @property
    def outcome_hash(self) -> str:
        return canonical_hash(self.payload)
