from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from itertools import combinations
from typing import Any, Mapping, Sequence

from app.domain.model_registry import FairValueQuote, ModelStatus, canonical_hash
from app.domain.pricing import (
    PricingOpportunity,
    american_odds_to_decimal,
    american_odds_to_implied_probability,
    expected_value_with_push,
    probability_edge,
)

QUALIFICATION_POLICY_VERSION = "ncaaf-qualification-v1"
RISK_POLICY_VERSION = "fractional-kelly-risk-budget-v1"
PARLAY_POLICY_VERSION = "cross-event-parlay-v1"
RECOMMENDATION_VERSION = "ncaaf-portfolio-recommendation-v1"
SIMULATOR_VERSION = "portfolio-simulator-v1"
MONEY_QUANTUM = Decimal("0.01")


class PortfolioState(StrEnum):
    NORMAL = "NORMAL"
    REDUCED_RISK = "REDUCED_RISK"
    PAUSED = "PAUSED"


class PositionClass(StrEnum):
    CORE = "CORE"
    OPPORTUNISTIC = "OPPORTUNISTIC"


@dataclass(frozen=True, slots=True)
class QualificationPolicy:
    minimum_ev: Decimal = Decimal("0.015")
    minimum_edge: Decimal = Decimal("0.0075")
    maximum_dispersion: Decimal = Decimal("0.06")
    minimum_books: int = 2
    maximum_market_age_seconds: int = 120
    core_minimum_ev: Decimal = Decimal("0.03")
    core_minimum_edge: Decimal = Decimal("0.015")
    allowed_model_statuses: frozenset[ModelStatus] = frozenset({ModelStatus.RETAINED_BENCHMARK})
    version: str = QUALIFICATION_POLICY_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("minimum_ev", self.minimum_ev),
            ("minimum_edge", self.minimum_edge),
            ("maximum_dispersion", self.maximum_dispersion),
            ("core_minimum_ev", self.core_minimum_ev),
            ("core_minimum_edge", self.core_minimum_edge),
        ):
            _finite_nonnegative(value, name)
        if self.minimum_books < 2 or self.maximum_market_age_seconds <= 0:
            raise ValueError("Qualification book and freshness limits must be positive")
        if any(value > 1 for value in (self.minimum_edge, self.maximum_dispersion, self.core_minimum_edge)):
            raise ValueError("Qualification probability fractions cannot exceed one")
        if self.core_minimum_ev < self.minimum_ev or self.core_minimum_edge < self.minimum_edge:
            raise ValueError("CORE thresholds cannot be below qualification thresholds")


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    kelly_fraction: Decimal = Decimal("0.25")
    minimum_stake: Decimal = Decimal("1.00")
    maximum_stake: Decimal = Decimal("50.00")
    maximum_core_bet_fraction: Decimal = Decimal("0.02")
    maximum_opportunistic_bet_fraction: Decimal = Decimal("0.01")
    maximum_daily_fraction: Decimal = Decimal("0.08")
    maximum_game_fraction: Decimal = Decimal("0.04")
    maximum_team_fraction: Decimal = Decimal("0.05")
    maximum_market_fraction: Decimal = Decimal("0.05")
    maximum_correlated_fraction: Decimal = Decimal("0.04")
    unit_fraction: Decimal = Decimal("0.04")
    opportunistic_multiplier: Decimal = Decimal("0.60")
    moderate_uncertainty_multiplier: Decimal = Decimal("0.75")
    high_uncertainty_multiplier: Decimal = Decimal("0.40")
    reduced_risk_multiplier: Decimal = Decimal("0.50")
    reduced_risk_drawdown: Decimal = Decimal("0.10")
    paused_drawdown: Decimal = Decimal("0.20")
    bankroll_floor_fraction_of_start: Decimal = Decimal("0.50")
    version: str = RISK_POLICY_VERSION

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name == "version":
                continue
            _finite_nonnegative(value, name)
        if self.kelly_fraction >= 1:
            raise ValueError("Full Kelly is prohibited")
        if self.minimum_stake <= 0 or self.maximum_stake < self.minimum_stake:
            raise ValueError("Stake boundaries must be positive and ordered")
        for field in (
            self.maximum_core_bet_fraction,
            self.maximum_opportunistic_bet_fraction,
            self.maximum_daily_fraction,
            self.maximum_game_fraction,
            self.maximum_team_fraction,
            self.maximum_market_fraction,
            self.maximum_correlated_fraction,
            self.unit_fraction,
            self.reduced_risk_drawdown,
            self.paused_drawdown,
            self.bankroll_floor_fraction_of_start,
        ):
            if field > 1:
                raise ValueError("Risk fractions cannot exceed one")
        if self.reduced_risk_drawdown >= self.paused_drawdown:
            raise ValueError("Reduced-risk drawdown must be below paused drawdown")
        if any(
            value > 1
            for value in (
                self.opportunistic_multiplier,
                self.moderate_uncertainty_multiplier,
                self.high_uncertainty_multiplier,
                self.reduced_risk_multiplier,
            )
        ):
            raise ValueError("Risk multipliers cannot exceed one")


@dataclass(frozen=True, slots=True)
class ParlayPolicy:
    enabled: bool = True
    minimum_legs: int = 2
    maximum_legs: int = 3
    minimum_joint_ev: Decimal = Decimal("0.05")
    kelly_fraction: Decimal = Decimal("0.10")
    maximum_parlay_fraction: Decimal = Decimal("0.005")
    maximum_daily_parlay_fraction: Decimal = Decimal("0.01")
    duplicate_exposure_penalty: Decimal = Decimal("0.25")
    version: str = PARLAY_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.minimum_legs != 2 or self.maximum_legs != 3:
            raise ValueError("Parlay v1 supports only two or three legs")
        for name, value in (
            ("minimum_joint_ev", self.minimum_joint_ev),
            ("kelly_fraction", self.kelly_fraction),
            ("maximum_parlay_fraction", self.maximum_parlay_fraction),
            ("maximum_daily_parlay_fraction", self.maximum_daily_parlay_fraction),
            ("duplicate_exposure_penalty", self.duplicate_exposure_penalty),
        ):
            _finite_nonnegative(value, name)
        if self.kelly_fraction >= 1 or self.maximum_parlay_fraction > Decimal("0.0075"):
            raise ValueError("Parlay risk must remain fractional and capped at 0.75%")
        if self.maximum_daily_parlay_fraction < self.maximum_parlay_fraction:
            raise ValueError("Daily parlay sleeve cannot be below the per-parlay cap")


@dataclass(frozen=True, slots=True)
class OpenExposure:
    event_id: str
    teams: tuple[str, ...]
    market_type: str
    selection_side: str
    stake: Decimal
    bet_kind: str = "straight"
    correlation_keys: tuple[str, ...] = ()
    slate_date: date | None = None


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    portfolio_id: str
    slate_date: date
    starting_bankroll: Decimal
    cash: Decimal
    reserved_exposure: Decimal
    equity: Decimal
    peak_equity: Decimal
    realized_pnl: Decimal
    open_exposures: tuple[OpenExposure, ...] = ()

    @property
    def drawdown_fraction(self) -> Decimal:
        if self.peak_equity <= 0:
            return Decimal(0)
        return max(Decimal(0), (self.peak_equity - self.equity) / self.peak_equity)


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    candidate_id: str
    fair_value: FairValueQuote
    opportunity: PricingOpportunity
    implied_probability: Decimal
    win_probability: Decimal
    push_probability: Decimal
    loss_probability: Decimal
    edge: Decimal
    ev_per_unit: Decimal
    classification: PositionClass | None
    qualified: bool
    rejection_reasons: tuple[str, ...]
    quality_multiplier: Decimal
    ranking_score: Decimal


@dataclass(frozen=True, slots=True)
class StraightRecommendation:
    candidate: CandidateEvaluation
    recommended_stake: Decimal
    bankroll_fraction: Decimal
    units: Decimal
    raw_kelly_fraction: Decimal
    adjusted_kelly_fraction: Decimal
    risk_adjustments: tuple[str, ...]
    recommendation_hash: str


@dataclass(frozen=True, slots=True)
class ParlayOffer:
    offer_id: str
    sportsbook_key: str
    leg_candidate_ids: tuple[str, ...]
    leg_observation_ids: tuple[str, ...]
    american_odds: int
    observed_at: datetime
    provenance: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ParlayRecommendation:
    offer: ParlayOffer
    legs: tuple[StraightRecommendation, ...]
    joint_fair_probability: Decimal
    implied_probability: Decimal
    joint_ev_per_unit: Decimal
    correlation_method: str
    correlation_adjustment: Decimal
    stake: Decimal
    bankroll_fraction: Decimal
    units: Decimal
    expected_net_profit: Decimal
    incremental_exposure: Mapping[str, Decimal]
    selection_score: Decimal
    recommendation_hash: str


@dataclass(frozen=True, slots=True)
class PortfolioDecision:
    portfolio_state: PortfolioState
    straight_recommendations: tuple[StraightRecommendation, ...]
    parlay: ParlayRecommendation | None
    pass_reasons: tuple[str, ...]
    evaluated_candidates: tuple[CandidateEvaluation, ...]
    qualification_policy_version: str
    risk_policy_version: str
    parlay_policy_version: str
    decision_hash: str


def portfolio_state(snapshot: PortfolioSnapshot, policy: RiskPolicy) -> PortfolioState:
    floor = snapshot.starting_bankroll * policy.bankroll_floor_fraction_of_start
    if snapshot.equity <= floor or snapshot.drawdown_fraction >= policy.paused_drawdown:
        return PortfolioState.PAUSED
    if snapshot.drawdown_fraction >= policy.reduced_risk_drawdown:
        return PortfolioState.REDUCED_RISK
    return PortfolioState.NORMAL


def fractional_kelly_with_push(
    win_probability: Decimal,
    push_probability: Decimal,
    decimal_odds: Decimal,
) -> Decimal:
    win = _probability(win_probability, "win_probability")
    push = _probability(push_probability, "push_probability")
    if win + push > 1:
        raise ValueError("Win and push probabilities cannot exceed one")
    loss = Decimal(1) - win - push
    b = decimal_odds - Decimal(1)
    if not decimal_odds.is_finite() or b <= 0:
        raise ValueError("Decimal odds must exceed one")
    resolved = win + loss
    if resolved == 0:
        return Decimal(0)
    return max(Decimal(0), (b * win - loss) / (b * resolved))


def evaluate_candidate(
    fair_value: FairValueQuote,
    opportunity: PricingOpportunity,
    policy: QualificationPolicy,
    *,
    as_of: datetime,
) -> CandidateEvaluation:
    reasons: list[str] = []
    if fair_value.canonical_event_id != opportunity.event_id:
        reasons.append("event_identity_mismatch")
    if fair_value.market_type != opportunity.market_type or fair_value.selection_side != opportunity.selection_side:
        reasons.append("market_identity_mismatch")
    if fair_value.fair_point != opportunity.point:
        reasons.append("exact_point_mismatch")
    if fair_value.model_status not in policy.allowed_model_statuses:
        reasons.append("model_status_not_eligible")
    if fair_value.fair_probability is None:
        reasons.append("fair_probability_unavailable")
    if fair_value.source_book_count < policy.minimum_books:
        reasons.append("insufficient_book_depth")
    dispersion = fair_value.consensus_dispersion
    if dispersion is None or dispersion > policy.maximum_dispersion:
        reasons.append("excessive_or_unknown_dispersion")
    age = (_utc(as_of) - _utc(fair_value.source_as_of)).total_seconds()
    if age < 0 or age > policy.maximum_market_age_seconds:
        reasons.append("stale_or_future_fair_value")
    if opportunity.quality_warnings:
        reasons.append("pricing_quality_warning")

    win = fair_value.fair_probability or Decimal(0)
    push = fair_value.push_probability or Decimal(0)
    if win + push > 1:
        reasons.append("invalid_probability_mass")
        loss = Decimal(0)
    else:
        loss = Decimal(1) - win - push
    implied = american_odds_to_implied_probability(opportunity.best_american_odds)
    edge = probability_edge(win, implied)
    ev = expected_value_with_push(win, loss, opportunity.best_decimal_odds)
    if edge < policy.minimum_edge:
        reasons.append("below_minimum_edge")
    if ev < policy.minimum_ev:
        reasons.append("below_minimum_ev")

    uncertainty = str(fair_value.uncertainty_quality.get("uncertainty", opportunity.uncertainty_indicator))
    multiplier = {"low": Decimal(1), "moderate": Decimal("0.75"), "high": Decimal("0.40")}.get(
        uncertainty,
        Decimal("0.60"),
    )
    classification = None
    if not reasons:
        classification = (
            PositionClass.CORE
            if ev >= policy.core_minimum_ev and edge >= policy.core_minimum_edge and uncertainty != "high"
            else PositionClass.OPPORTUNISTIC
        )
    candidate_id = canonical_hash(
        {
            "fair_value_hash": fair_value.fair_value_hash,
            "observation_id": str(opportunity.best_executable_observation_id),
            "odds": opportunity.best_american_odds,
            "point": opportunity.point,
        }
    )
    score = ev * multiplier / (Decimal(1) + (dispersion or Decimal(0)) * Decimal(10))
    return CandidateEvaluation(
        candidate_id=candidate_id,
        fair_value=fair_value,
        opportunity=opportunity,
        implied_probability=implied,
        win_probability=win,
        push_probability=push,
        loss_probability=loss,
        edge=edge,
        ev_per_unit=ev,
        classification=classification,
        qualified=not reasons,
        rejection_reasons=tuple(reasons),
        quality_multiplier=multiplier,
        ranking_score=score,
    )


def construct_portfolio(
    candidates: Sequence[CandidateEvaluation],
    snapshot: PortfolioSnapshot,
    *,
    top_n: int,
    risk_policy: RiskPolicy,
    qualification_policy: QualificationPolicy,
    parlay_policy: ParlayPolicy,
    parlay_offers: Sequence[ParlayOffer] = (),
) -> PortfolioDecision:
    if top_n < 1 or top_n > 10:
        raise ValueError("Top N must be between one and ten")
    state = portfolio_state(snapshot, risk_policy)
    qualified = sorted(
        (item for item in candidates if item.qualified),
        key=lambda item: (
            item.classification != PositionClass.CORE,
            -item.ranking_score,
            -item.ev_per_unit,
            item.opportunity.scheduled_start_utc,
            item.candidate_id,
        ),
    )
    recommendations: list[StraightRecommendation] = []
    pass_reasons: list[str] = []
    if state == PortfolioState.PAUSED:
        pass_reasons.append("portfolio_paused_by_drawdown_or_bankroll_floor")
    else:
        for candidate in qualified:
            if len(recommendations) >= top_n:
                break
            recommendation, reason = _size_candidate(candidate, snapshot, recommendations, state, risk_policy)
            if recommendation is None:
                pass_reasons.append(reason)
            else:
                recommendations.append(recommendation)
    if not qualified:
        pass_reasons.append("no_candidates_passed_qualification")
    if not recommendations:
        pass_reasons.append("no_straight_positions_after_risk_controls")

    parlay, parlay_reason = optimize_parlay(
        recommendations,
        parlay_offers,
        snapshot,
        state=state,
        risk_policy=risk_policy,
        policy=parlay_policy,
    )
    if parlay is None:
        pass_reasons.append(f"parlay_pass:{parlay_reason}")
    pass_reasons = sorted(set(pass_reasons))
    payload = {
        "state": state.value,
        "straight_hashes": [item.recommendation_hash for item in recommendations],
        "parlay_hash": parlay.recommendation_hash if parlay else None,
        "pass_reasons": pass_reasons,
        "qualification_policy": qualification_policy.version,
        "risk_policy": risk_policy.version,
        "parlay_policy": parlay_policy.version,
    }
    return PortfolioDecision(
        portfolio_state=state,
        straight_recommendations=tuple(recommendations),
        parlay=parlay,
        pass_reasons=tuple(pass_reasons),
        evaluated_candidates=tuple(candidates),
        qualification_policy_version=qualification_policy.version,
        risk_policy_version=risk_policy.version,
        parlay_policy_version=parlay_policy.version,
        decision_hash=canonical_hash(payload),
    )


def optimize_parlay(
    recommendations: Sequence[StraightRecommendation],
    offers: Sequence[ParlayOffer],
    snapshot: PortfolioSnapshot,
    *,
    state: PortfolioState,
    risk_policy: RiskPolicy,
    policy: ParlayPolicy,
) -> tuple[ParlayRecommendation | None, str]:
    if not policy.enabled:
        return None, "sleeve_disabled"
    if state == PortfolioState.PAUSED:
        return None, "portfolio_paused"
    by_id = {item.candidate.candidate_id: item for item in recommendations}
    eligible: list[ParlayRecommendation] = []
    for offer in sorted(offers, key=lambda item: item.offer_id):
        if len(offer.leg_candidate_ids) not in range(policy.minimum_legs, policy.maximum_legs + 1):
            continue
        if len(set(offer.leg_candidate_ids)) != len(offer.leg_candidate_ids):
            continue
        legs = tuple(by_id[item] for item in offer.leg_candidate_ids if item in by_id)
        if len(legs) != len(offer.leg_candidate_ids) or any(not item.candidate.qualified for item in legs):
            continue
        if len(offer.leg_observation_ids) != len(legs):
            continue
        if any(
            observation_id not in {str(value) for value in leg.candidate.opportunity.source_observation_ids}
            for observation_id, leg in zip(offer.leg_observation_ids, legs, strict=True)
        ):
            continue
        events = [str(item.candidate.opportunity.event_id) for item in legs]
        teams = [
            {item.candidate.opportunity.home_team, item.candidate.opportunity.away_team}
            for item in legs
        ]
        if len(set(events)) != len(events) or any(left & right for left, right in combinations(teams, 2)):
            # V1 has no validated same-game/shared-team joint model.
            continue
        joint = Decimal(1)
        for leg in legs:
            joint *= leg.candidate.win_probability
        implied = american_odds_to_implied_probability(offer.american_odds)
        decimal_odds = american_odds_to_decimal(offer.american_odds)
        joint_ev = expected_value_with_push(joint, Decimal(1) - joint, decimal_odds)
        if joint_ev < policy.minimum_joint_ev:
            continue
        raw_kelly = fractional_kelly_with_push(joint, Decimal(0), decimal_odds)
        fraction = min(raw_kelly * policy.kelly_fraction, policy.maximum_parlay_fraction)
        if state == PortfolioState.REDUCED_RISK:
            fraction *= risk_policy.reduced_risk_multiplier
        straight_events = {str(item.candidate.opportunity.event_id) for item in recommendations}
        duplicate_count = sum(1 for event in events if event in straight_events)
        existing_exposures = list(snapshot.open_exposures)
        existing_exposures.extend(
            OpenExposure(
                event_id=str(item.candidate.opportunity.event_id),
                teams=(item.candidate.opportunity.home_team, item.candidate.opportunity.away_team),
                market_type=item.candidate.opportunity.market_type,
                selection_side=item.candidate.opportunity.selection_side,
                stake=item.recommended_stake,
                slate_date=snapshot.slate_date,
            )
            for item in recommendations
        )
        remaining_daily = max(
            Decimal(0),
            snapshot.equity * risk_policy.maximum_daily_fraction
            - _exposure_sum(existing_exposures, lambda item: item.slate_date == snapshot.slate_date),
        )
        remaining_parlay = max(
            Decimal(0),
            snapshot.equity * policy.maximum_daily_parlay_fraction
            - _exposure_sum(
                existing_exposures,
                lambda item: item.bet_kind == "parlay" and item.slate_date == snapshot.slate_date,
            ),
        )
        per_leg_caps: list[Decimal] = []
        for leg in legs:
            event_id = str(leg.candidate.opportunity.event_id)
            per_leg_caps.append(
                snapshot.equity * risk_policy.maximum_game_fraction
                - _exposure_sum(existing_exposures, lambda item, event_id=event_id: item.event_id == event_id)
            )
            for team in (leg.candidate.opportunity.home_team, leg.candidate.opportunity.away_team):
                per_leg_caps.append(
                    snapshot.equity * risk_policy.maximum_team_fraction
                    - _exposure_sum(existing_exposures, lambda item, team=team: team in item.teams)
                )
        stake = _money(
            min(
                snapshot.equity * fraction,
                remaining_daily,
                remaining_parlay,
                snapshot.cash,
                *per_leg_caps,
            )
        )
        if stake < risk_policy.minimum_stake:
            continue
        selection_score = joint_ev - Decimal("0.01") * duplicate_count
        payload = {
            "offer_id": offer.offer_id,
            "legs": [item.recommendation_hash for item in legs],
            "joint_probability": joint,
            "odds": offer.american_odds,
            "stake": stake,
            "policy": policy.version,
        }
        eligible.append(
            ParlayRecommendation(
                offer=offer,
                legs=legs,
                joint_fair_probability=joint,
                implied_probability=implied,
                joint_ev_per_unit=joint_ev,
                correlation_method="cross-event-disjoint-team-independence-v1",
                correlation_adjustment=Decimal(0),
                stake=stake,
                bankroll_fraction=stake / snapshot.equity,
                units=stake / (snapshot.equity * risk_policy.unit_fraction),
                expected_net_profit=stake * joint_ev,
                incremental_exposure={event: stake for event in sorted(events)},
                selection_score=selection_score,
                recommendation_hash=canonical_hash(payload),
            )
        )
    if not eligible:
        return None, "no_verified_positive_ev_joint_quote"
    eligible.sort(key=lambda item: (-item.selection_score, item.recommendation_hash))
    return eligible[0], "selected"


def _size_candidate(
    candidate: CandidateEvaluation,
    snapshot: PortfolioSnapshot,
    selected: Sequence[StraightRecommendation],
    state: PortfolioState,
    policy: RiskPolicy,
) -> tuple[StraightRecommendation | None, str]:
    opportunity = candidate.opportunity
    all_exposures = list(snapshot.open_exposures)
    all_exposures.extend(
        OpenExposure(
            event_id=str(item.candidate.opportunity.event_id),
            teams=(item.candidate.opportunity.home_team, item.candidate.opportunity.away_team),
            market_type=item.candidate.opportunity.market_type,
            selection_side=item.candidate.opportunity.selection_side,
            stake=item.recommended_stake,
            slate_date=snapshot.slate_date,
        )
        for item in selected
    )
    event_id = str(opportunity.event_id)
    opposing = [
        item
        for item in all_exposures
        if item.event_id == event_id
        and item.market_type == opportunity.market_type
        and item.selection_side != opportunity.selection_side
    ]
    if opposing:
        return None, f"opposing_position_rejected:{candidate.candidate_id}"

    decimal_odds = opportunity.best_decimal_odds
    raw_kelly = fractional_kelly_with_push(candidate.win_probability, candidate.push_probability, decimal_odds)
    multiplier = candidate.quality_multiplier
    adjustments = [f"quality_multiplier:{multiplier}", f"fractional_kelly:{policy.kelly_fraction}"]
    if candidate.classification == PositionClass.OPPORTUNISTIC:
        multiplier *= policy.opportunistic_multiplier
        adjustments.append(f"opportunistic_multiplier:{policy.opportunistic_multiplier}")
    if state == PortfolioState.REDUCED_RISK:
        multiplier *= policy.reduced_risk_multiplier
        adjustments.append(f"reduced_risk_multiplier:{policy.reduced_risk_multiplier}")
    adjusted = raw_kelly * policy.kelly_fraction * multiplier
    per_bet_fraction = (
        policy.maximum_core_bet_fraction
        if candidate.classification == PositionClass.CORE
        else policy.maximum_opportunistic_bet_fraction
    )
    caps = {
        "per_bet": snapshot.equity * per_bet_fraction,
        "fixed_maximum": policy.maximum_stake,
        "available_cash": snapshot.cash - sum((item.recommended_stake for item in selected), Decimal(0)),
        "daily": snapshot.equity * policy.maximum_daily_fraction
        - _exposure_sum(all_exposures, lambda item: item.slate_date == snapshot.slate_date),
        "game": snapshot.equity * policy.maximum_game_fraction
        - _exposure_sum(all_exposures, lambda item: item.event_id == event_id),
        "team": min(
            snapshot.equity * policy.maximum_team_fraction
            - _exposure_sum(all_exposures, lambda item, team=team: team in item.teams)
            for team in (opportunity.home_team, opportunity.away_team)
        ),
        "market": snapshot.equity * policy.maximum_market_fraction
        - _exposure_sum(all_exposures, lambda item: item.market_type == opportunity.market_type),
        "correlated": snapshot.equity * policy.maximum_correlated_fraction
        - _exposure_sum(all_exposures, lambda item: item.event_id == event_id),
    }
    target = snapshot.equity * adjusted
    limiting_name, limiting_value = min(caps.items(), key=lambda item: item[1])
    stake = _money(max(Decimal(0), min(target, limiting_value)))
    if limiting_value < target:
        adjustments.append(f"cap:{limiting_name}")
    if stake < policy.minimum_stake:
        return None, f"stake_below_minimum_after_risk:{candidate.candidate_id}"
    payload = {
        "candidate_id": candidate.candidate_id,
        "stake": stake,
        "classification": candidate.classification,
        "risk_policy": policy.version,
        "adjustments": adjustments,
    }
    unit_value = snapshot.equity * policy.unit_fraction
    return (
        StraightRecommendation(
            candidate=candidate,
            recommended_stake=stake,
            bankroll_fraction=stake / snapshot.equity,
            units=stake / unit_value,
            raw_kelly_fraction=raw_kelly,
            adjusted_kelly_fraction=adjusted,
            risk_adjustments=tuple(adjustments),
            recommendation_hash=canonical_hash(payload),
        ),
        "selected",
    )


def _exposure_sum(items: Sequence[OpenExposure], predicate: Any) -> Decimal:
    return sum((item.stake for item in items if predicate(item)), Decimal(0))


def _finite_nonnegative(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


def _probability(value: Decimal, name: str) -> Decimal:
    if not value.is_finite() or value < 0 or value > 1:
        raise ValueError(f"{name} must be between zero and one")
    return value


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_DOWN)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Portfolio decision timestamps must be timezone-aware")
    return value.astimezone(UTC)
