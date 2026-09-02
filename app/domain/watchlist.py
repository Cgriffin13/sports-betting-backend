from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Sequence

from app.domain.portfolio_engine import CandidateEvaluation, QualificationPolicy

WATCHLIST_VERSION = "ncaaf-watchlist-v2"
MAXIMUM_FAILED_GATES = 2
MAXIMUM_TOTAL_DISTANCE = Decimal("0.75")
MAXIMUM_SINGLE_GATE_DISTANCE = Decimal("0.50")
WATCHLIST_BLOCKERS = frozenset(
    {
        "below_minimum_ev",
        "below_minimum_edge",
        "insufficient_book_depth",
        "excessive_or_unknown_dispersion",
        "stale_or_future_fair_value",
        "pricing_quality_warning",
    }
)


def build_watchlist(
    candidates: Sequence[CandidateEvaluation],
    policy: QualificationPolicy,
    *,
    as_of: datetime,
    timing: dict[str, Any],
) -> list[dict[str, Any]]:
    """Rank research-only near misses from the existing pricing/evaluation path.

    Eligibility is intentionally bounded by the Phase 4 pricing baseline: a row must
    already be a structurally valid positive-edge, positive-EV pricing opportunity.
    This function does not relax or recompute production qualification.
    """
    cutoff = _utc(as_of)
    rows: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for candidate in candidates:
        blockers = tuple(candidate.rejection_reasons)
        if candidate.qualified or not blockers or not set(blockers).issubset(WATCHLIST_BLOCKERS):
            continue
        if candidate.edge <= 0 or candidate.ev_per_unit <= 0:
            continue
        opportunity = candidate.opportunity
        if _utc(opportunity.scheduled_start_utc) <= cutoff:
            continue
        distances = _distances(candidate, policy, cutoff)
        total_distance = sum(distances.values(), Decimal(0))
        if (
            len(blockers) > MAXIMUM_FAILED_GATES
            or total_distance > MAXIMUM_TOTAL_DISTANCE
            or max(distances.values(), default=Decimal(0)) > MAXIMUM_SINGLE_GATE_DISTANCE
        ):
            continue
        primary = max(blockers, key=lambda reason: (distances.get(reason, Decimal(1)), reason))
        observed_times = [item.selection_observed_at for item in opportunity.book_probabilities if item.selection_observed_at]
        latest_observed = max((_utc(value) for value in observed_times), default=cutoff)
        age_seconds = max(0, int((cutoff - latest_observed).total_seconds()))
        item = {
            "watchlist_id": candidate.candidate_id,
            "event_id": str(opportunity.event_id),
            "slate_date": _utc(opportunity.scheduled_start_utc).date().isoformat(),
            "scheduled_start": _utc(opportunity.scheduled_start_utc).isoformat(),
            "home_team": opportunity.home_team,
            "away_team": opportunity.away_team,
            "market": opportunity.market_type,
            "side": opportunity.selection_side,
            "selection": opportunity.selection_name,
            "sportsbook": opportunity.best_sportsbook_key,
            "point": _number(opportunity.point),
            "odds": opportunity.best_american_odds,
            "fair_probability": _number(candidate.win_probability),
            "implied_probability": _number(candidate.implied_probability),
            "edge": _number(candidate.edge),
            "ev_per_unit": _number(candidate.ev_per_unit),
            "books_count": opportunity.books_contributing,
            "dispersion": _number(opportunity.consensus_dispersion),
            "freshness_age_seconds": age_seconds,
            "fresh": age_seconds <= policy.maximum_market_age_seconds,
            "timing_classification": timing["timing_classification"],
            "primary_horizon_at": _utc(timing["primary_horizon_at"]).isoformat(),
            "rejection_reasons": list(blockers),
            "primary_blocker": primary,
            "failed_gate_count": len(blockers),
            "distance_to_qualification": _number(total_distance),
            "ranking_score": _number(Decimal(1) / (Decimal(1) + total_distance)),
            "source_observation_ids": [str(value) for value in opportunity.source_observation_ids],
            "snapshot_ids": [str(value) for value in opportunity.snapshot_ids],
            "best_executable_observation_id": str(opportunity.best_executable_observation_id),
            "watchlist_version": WATCHLIST_VERSION,
            "actionable": False,
        }
        sort_key = (
            len(blockers),
            total_distance,
            -candidate.ev_per_unit,
            -candidate.edge,
            _utc(opportunity.scheduled_start_utc),
            candidate.candidate_id,
        )
        rows.append((sort_key, item))
    rows.sort(key=lambda value: value[0])
    return [item for _, item in rows]


def _distances(
    candidate: CandidateEvaluation,
    policy: QualificationPolicy,
    as_of: datetime,
) -> dict[str, Decimal]:
    fair_value = candidate.fair_value
    dispersion = fair_value.consensus_dispersion
    age = Decimal(str((_utc(as_of) - _utc(fair_value.source_as_of)).total_seconds()))
    distances: dict[str, Decimal] = {}
    for reason in candidate.rejection_reasons:
        if reason == "below_minimum_ev":
            distances[reason] = _shortfall(candidate.ev_per_unit, policy.minimum_ev)
        elif reason == "below_minimum_edge":
            distances[reason] = _shortfall(candidate.edge, policy.minimum_edge)
        elif reason == "insufficient_book_depth":
            distances[reason] = Decimal(policy.minimum_books - fair_value.source_book_count) / Decimal(
                policy.minimum_books
            )
        elif reason == "excessive_or_unknown_dispersion":
            distances[reason] = Decimal(1) if dispersion is None else max(
                Decimal(0), (dispersion - policy.maximum_dispersion) / policy.maximum_dispersion
            )
        elif reason == "stale_or_future_fair_value":
            maximum_age = Decimal(policy.maximum_market_age_seconds)
            distances[reason] = abs(age - maximum_age) / maximum_age
        else:
            distances[reason] = Decimal(1)
    return distances


def _shortfall(value: Decimal, threshold: Decimal) -> Decimal:
    return max(Decimal(0), (threshold - value) / threshold) if threshold > 0 else Decimal(0)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Watchlist timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
