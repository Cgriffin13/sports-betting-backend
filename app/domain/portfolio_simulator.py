from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from app.domain.portfolio_engine import (
    CandidateEvaluation,
    ParlayOffer,
    ParlayPolicy,
    PortfolioSnapshot,
    QualificationPolicy,
    RiskPolicy,
    SIMULATOR_VERSION,
    construct_portfolio,
)


@dataclass(frozen=True, slots=True)
class SimulationOutcome:
    candidate_id: str
    result: str
    known_at: datetime

    def __post_init__(self) -> None:
        if self.result not in {"win", "loss", "push"}:
            raise ValueError("Simulation outcome must be win, loss, or push")
        if self.known_at.tzinfo is None:
            raise ValueError("Simulation outcome timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SimulationSlate:
    as_of: datetime
    candidates: tuple[CandidateEvaluation, ...]
    outcomes: tuple[SimulationOutcome, ...]
    parlay_offers: tuple[ParlayOffer, ...] = ()


@dataclass(frozen=True, slots=True)
class SimulationResult:
    starting_bankroll: Decimal
    ending_bankroll: Decimal
    realized_pnl: Decimal
    turnover: Decimal
    maximum_drawdown: Decimal
    straight_bets: int
    parlay_bets: int
    pass_slates: int
    decision_hashes: tuple[str, ...]
    simulator_version: str = SIMULATOR_VERSION


def simulate_portfolio(
    slates: Sequence[SimulationSlate],
    *,
    starting_bankroll: Decimal,
    top_n: int,
    qualification_policy: QualificationPolicy,
    risk_policy: RiskPolicy,
    parlay_policy: ParlayPolicy,
) -> SimulationResult:
    if not starting_bankroll.is_finite() or starting_bankroll <= 0:
        raise ValueError("Simulation bankroll must be finite and positive")
    ordered = sorted(slates, key=lambda item: item.as_of)
    bankroll = starting_bankroll
    peak = bankroll
    maximum_drawdown = Decimal(0)
    turnover = Decimal(0)
    straight_count = 0
    parlay_count = 0
    pass_count = 0
    hashes: list[str] = []
    previous_as_of: datetime | None = None
    for slate in ordered:
        if slate.as_of.tzinfo is None:
            raise ValueError("Simulation cutoff must be timezone-aware")
        if previous_as_of is not None and slate.as_of <= previous_as_of:
            raise ValueError("Simulation slates must have unique chronological cutoffs")
        previous_as_of = slate.as_of
        outcome_by_id = {item.candidate_id: item for item in slate.outcomes}
        if any(item.known_at <= slate.as_of for item in slate.outcomes):
            raise ValueError("Outcomes must not be available at the decision cutoff")
        snapshot = PortfolioSnapshot(
            portfolio_id="offline-simulation",
            slate_date=slate.as_of.date(),
            starting_bankroll=starting_bankroll,
            cash=bankroll,
            reserved_exposure=Decimal(0),
            equity=bankroll,
            peak_equity=peak,
            realized_pnl=bankroll - starting_bankroll,
        )
        decision = construct_portfolio(
            slate.candidates,
            snapshot,
            top_n=top_n,
            risk_policy=risk_policy,
            qualification_policy=qualification_policy,
            parlay_policy=parlay_policy,
            parlay_offers=slate.parlay_offers,
        )
        hashes.append(decision.decision_hash)
        if not decision.straight_recommendations and decision.parlay is None:
            pass_count += 1
        for recommendation in decision.straight_recommendations:
            outcome = outcome_by_id.get(recommendation.candidate.candidate_id)
            if outcome is None:
                raise ValueError("Every simulated straight recommendation requires a later outcome")
            stake = recommendation.recommended_stake
            turnover += stake
            straight_count += 1
            bankroll += _net_pnl(outcome.result, stake, recommendation.candidate.opportunity.best_decimal_odds)
        if decision.parlay is not None:
            results = [outcome_by_id.get(item.candidate.candidate_id) for item in decision.parlay.legs]
            if any(item is None for item in results):
                raise ValueError("Every simulated parlay leg requires a later outcome")
            if any(item.result == "push" for item in results if item is not None):
                raise ValueError("Parlay push repricing requires a provider payout contract")
            parlay_result = "win" if all(item.result == "win" for item in results if item is not None) else "loss"
            turnover += decision.parlay.stake
            parlay_count += 1
            bankroll += _net_pnl(
                parlay_result,
                decision.parlay.stake,
                Decimal(1) / decision.parlay.implied_probability,
            )
        peak = max(peak, bankroll)
        maximum_drawdown = max(maximum_drawdown, (peak - bankroll) / peak if peak else Decimal(0))
    return SimulationResult(
        starting_bankroll=starting_bankroll,
        ending_bankroll=bankroll,
        realized_pnl=bankroll - starting_bankroll,
        turnover=turnover,
        maximum_drawdown=maximum_drawdown,
        straight_bets=straight_count,
        parlay_bets=parlay_count,
        pass_slates=pass_count,
        decision_hashes=tuple(hashes),
    )


def _net_pnl(result: str, stake: Decimal, decimal_odds: Decimal) -> Decimal:
    if result == "win":
        return stake * (decimal_odds - Decimal(1))
    if result == "loss":
        return -stake
    return Decimal(0)
