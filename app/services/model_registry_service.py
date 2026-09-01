from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.db.model_registry_models import ModelRegistryEntry, ShadowPrediction, ShadowPredictionOutcome
from app.domain.model_registry import (
    ConsensusFairValueInput,
    FairValueQuote,
    ModelStatus,
    RegistryError,
    ShadowOutcomeDraft,
    ShadowPredictionDraft,
)
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository


class FairValueService:
    """Produce fair value only from an explicitly retained registry benchmark."""

    def quote(self, registration: ModelRegistryEntry, value: ConsensusFairValueInput) -> FairValueQuote:
        if registration.league != "NCAAF":
            raise RegistryError("NCAAF fair-value service requires an NCAAF registration")
        if registration.status != ModelStatus.RETAINED_BENCHMARK.value:
            raise RegistryError("only a retained benchmark may provide Phase 6 fair value")
        if registration.model_family != "market_consensus":
            raise RegistryError("diagnostic or rejected football models cannot provide fair value")
        expected_market = "spread" if registration.market_type == "margin" else registration.market_type
        if expected_market != value.market_type:
            raise RegistryError("registered model target does not match fair-value market")
        return FairValueQuote(
            canonical_event_id=value.canonical_event_id,
            model_id=registration.model_id,
            model_version=registration.version,
            model_status=ModelStatus(registration.status),
            market_type=value.market_type,
            selection_side=value.selection_side,
            fair_probability=value.fair_probability,
            fair_point=value.fair_point,
            push_probability=value.push_probability,
            uncertainty_quality=dict(value.quality_metadata),
            source_as_of=value.as_of,
            source_books=tuple(sorted(set(value.source_books))),
            source_book_count=len(set(value.source_books)),
            consensus_dispersion=value.consensus_dispersion,
            provenance={
                **dict(value.provenance),
                "registry_entry_hash": registration.registry_entry_hash,
                "consensus_version": registration.consensus_version,
                "vig_removal_version": registration.vig_removal_version,
                "fair_value_source": "market_consensus",
            },
        )


class ShadowPredictionService:
    def __init__(self, repository: SqlAlchemyModelRegistryRepository) -> None:
        self.repository = repository

    def record(self, draft: ShadowPredictionDraft) -> ShadowPrediction:
        return self.repository.append_prediction(draft)

    def plan_slate(self, slate_date_utc: date) -> "ShadowSlatePlan":
        events = self.repository.list_ncaaf_slate(slate_date_utc)
        if not events:
            return ShadowSlatePlan(slate_date_utc, None, ())
        kickoffs = tuple(_as_utc(item.scheduled_start_utc) for item in events)
        return ShadowSlatePlan(slate_date_utc, min(kickoffs) - timedelta(hours=3), tuple(str(item.id) for item in events))

    def attach_outcome(self, draft: ShadowOutcomeDraft) -> ShadowPredictionOutcome:
        prediction = self.repository.get_prediction(draft.prediction_id)
        if prediction is None:
            raise RegistryError("shadow prediction does not exist")
        margin = draft.final_home_score - draft.final_away_score
        total = draft.final_home_score + draft.final_away_score
        result = _settlement_result(
            market_type=prediction.market_type,
            side=prediction.selection_side,
            point=prediction.fair_point,
            margin=margin,
            total=total,
        )
        actual = Decimal(1) if result == "win" else Decimal(0)
        metrics: dict[str, Any] = {"actual_margin": margin, "actual_total": total}
        if prediction.fair_probability is not None and result != "push":
            error = prediction.fair_probability - actual
            metrics["brier"] = str(error * error)
        return self.repository.attach_outcome(draft, result=result, evaluation_metrics=metrics)


def _settlement_result(*, market_type: str, side: str, point: Decimal | None, margin: int, total: int) -> str:
    if market_type == "moneyline":
        if margin == 0:
            return "push"
        won = margin > 0 if side == "home" else margin < 0
        return "win" if won else "loss"
    if point is None:
        raise RegistryError("spread/total evaluation requires a point")
    value = Decimal(margin) + point if market_type == "spread" and side == "home" else None
    if market_type == "spread" and side == "away":
        value = Decimal(-margin) + point
    if market_type == "total":
        value = Decimal(total) - point if side == "over" else point - Decimal(total)
    if value is None:
        raise RegistryError("unsupported shadow settlement")
    return "win" if value > 0 else "loss" if value < 0 else "push"


@dataclass(frozen=True, slots=True)
class ShadowSlatePlan:
    slate_date_utc: date
    prediction_cutoff: datetime | None
    canonical_event_ids: tuple[str, ...]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
