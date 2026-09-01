from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.domain.model_registry import FairValueQuote, ModelStatus
from app.domain.portfolio_engine import (
    ParlayOffer,
    ParlayPolicy,
    PortfolioSnapshot,
    PortfolioState,
    PositionClass,
    QualificationPolicy,
    RiskPolicy,
    construct_portfolio,
    evaluate_candidate,
    fractional_kelly_with_push,
    optimize_parlay,
    portfolio_state,
)
from app.domain.pricing import BookNoVigPrice, PricingOpportunity, american_odds_to_decimal
from app.domain.portfolio_simulator import SimulationOutcome, SimulationSlate, simulate_portfolio

NOW = datetime(2026, 9, 5, 13, tzinfo=UTC)


def test_push_aware_ev_and_fractional_kelly_math() -> None:
    fraction = fractional_kelly_with_push(Decimal("0.55"), Decimal("0.05"), Decimal("2.0"))
    assert fraction == Decimal("0.1578947368421052631578947368")
    assert fraction > 0
    assert RiskPolicy().kelly_fraction == Decimal("0.25")
    with pytest.raises(ValueError, match="Full Kelly"):
        RiskPolicy(kelly_fraction=Decimal(1))


def test_candidate_keeps_fair_value_separate_from_best_executable_price() -> None:
    opportunity = _opportunity(odds=120, fair=Decimal("0.55"))
    quote = _quote(opportunity, fair=Decimal("0.55"))
    evaluation = evaluate_candidate(quote, opportunity, QualificationPolicy(), as_of=NOW)

    assert evaluation.qualified
    assert evaluation.win_probability == Decimal("0.55")
    assert evaluation.implied_probability == Decimal(100) / Decimal(220)
    assert evaluation.ev_per_unit == Decimal("0.21")
    assert evaluation.classification is PositionClass.CORE
    assert "american_odds" not in quote.payload


def test_exact_line_and_stale_quotes_fail_qualification() -> None:
    opportunity = _opportunity(market="spread", point=Decimal("-3.5"))
    mismatch = replace(_quote(opportunity), fair_point=Decimal("-4.0"))
    stale = replace(_quote(opportunity), source_as_of=NOW - timedelta(minutes=3))

    assert "exact_point_mismatch" in evaluate_candidate(
        mismatch, opportunity, QualificationPolicy(), as_of=NOW
    ).rejection_reasons
    assert "stale_or_future_fair_value" in evaluate_candidate(
        stale, opportunity, QualificationPolicy(), as_of=NOW
    ).rejection_reasons


def test_top_n_is_ceiling_and_zero_positions_is_valid() -> None:
    snapshot = _snapshot()
    unqualified = evaluate_candidate(
        _quote(_opportunity(fair=Decimal("0.45")), fair=Decimal("0.45")),
        _opportunity(fair=Decimal("0.45")),
        QualificationPolicy(),
        as_of=NOW,
    )
    decision = construct_portfolio(
        [unqualified], snapshot, top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )
    assert decision.straight_recommendations == ()
    assert decision.parlay is None
    assert "no_candidates_passed_qualification" in decision.pass_reasons
    assert any(reason.startswith("parlay_pass:") for reason in decision.pass_reasons)


def test_stake_caps_units_and_risk_states() -> None:
    opportunity = _opportunity(odds=200, fair=Decimal("0.60"))
    candidate = evaluate_candidate(_quote(opportunity, fair=Decimal("0.60")), opportunity, QualificationPolicy(), as_of=NOW)
    decision = construct_portfolio(
        [candidate], _snapshot(), top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )
    recommendation = decision.straight_recommendations[0]
    assert recommendation.recommended_stake == Decimal("4.00")  # 2% per-bet cap on $200 equity
    assert recommendation.bankroll_fraction == Decimal("0.02")
    assert recommendation.units == Decimal("0.5")  # one display unit = 4% of current equity
    assert portfolio_state(replace(_snapshot(), equity=Decimal("175"), peak_equity=Decimal("200")), RiskPolicy()) is PortfolioState.REDUCED_RISK
    assert portfolio_state(replace(_snapshot(), equity=Decimal("150"), peak_equity=Decimal("200")), RiskPolicy()) is PortfolioState.PAUSED


def test_opposing_positions_and_daily_cap_reduce_or_reject() -> None:
    first = _opportunity(side="home", odds=200, fair=Decimal("0.60"))
    second = _opportunity(event_id=first.event_id, side="away", odds=200, fair=Decimal("0.60"))
    candidates = [
        evaluate_candidate(_quote(item, fair=Decimal("0.60")), item, QualificationPolicy(), as_of=NOW)
        for item in (first, second)
    ]
    decision = construct_portfolio(
        candidates, _snapshot(), top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )
    assert len(decision.straight_recommendations) == 1
    assert any(reason.startswith("opposing_position_rejected") for reason in decision.pass_reasons)


def test_parlay_requires_verified_exact_legs_and_never_forces_selection() -> None:
    first = _qualified(_opportunity(event_id=uuid4(), home="A", away="B", odds=150, fair=Decimal("0.55")))
    second = _qualified(_opportunity(event_id=uuid4(), home="C", away="D", odds=140, fair=Decimal("0.54")))
    decision = construct_portfolio(
        [first, second], _snapshot(), top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )
    assert decision.parlay is None

    straight = decision.straight_recommendations
    offer = ParlayOffer(
        offer_id="quote-1",
        sportsbook_key="draftkings",
        leg_candidate_ids=tuple(item.candidate.candidate_id for item in straight),
        leg_observation_ids=tuple(str(item.candidate.opportunity.best_executable_observation_id) for item in straight),
        american_odds=500,
        observed_at=NOW,
        provenance={"verified_provider_quote": True, "source_snapshot_id": "snapshot"},
    )
    parlay, reason = optimize_parlay(
        straight, [offer], _snapshot(), state=PortfolioState.NORMAL,
        risk_policy=RiskPolicy(), policy=ParlayPolicy(),
    )
    assert reason == "selected"
    assert parlay is not None
    assert parlay.joint_fair_probability == Decimal("0.2970")
    assert parlay.joint_ev_per_unit == Decimal("0.7820")
    assert parlay.stake <= Decimal("1.00")  # 0.5% cap before duplicate-exposure penalty
    assert parlay.correlation_method == "cross-event-disjoint-team-independence-v1"


def test_same_game_parlay_is_rejected_without_correlation_model() -> None:
    event_id = uuid4()
    first = _qualified(_opportunity(event_id=event_id, market="spread", point=Decimal("-3.5"), side="home"))
    second = _qualified(_opportunity(event_id=event_id, market="total", point=Decimal("52.5"), side="over"))
    straight = construct_portfolio(
        [first, second], _snapshot(), top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    ).straight_recommendations
    offer = ParlayOffer(
        "same-game", "draftkings", tuple(item.candidate.candidate_id for item in straight),
        tuple(str(item.candidate.opportunity.best_executable_observation_id) for item in straight),
        300, NOW, {"verified_provider_quote": True, "source_snapshot_id": "x"},
    )
    assert optimize_parlay(straight, [offer], _snapshot(), state=PortfolioState.NORMAL, risk_policy=RiskPolicy(), policy=ParlayPolicy())[0] is None


def test_simulator_is_deterministic_and_rejects_outcome_leakage() -> None:
    candidate = _qualified(_opportunity(odds=120, fair=Decimal("0.55")))
    outcome = SimulationOutcome(candidate.candidate_id, "win", NOW + timedelta(hours=10))
    slate = SimulationSlate(NOW, (candidate,), (outcome,))
    def run(items: list[SimulationSlate]):
        return simulate_portfolio(
            items,
            starting_bankroll=Decimal("200"),
            top_n=10,
            qualification_policy=QualificationPolicy(),
            risk_policy=RiskPolicy(),
            parlay_policy=ParlayPolicy(),
        )

    assert run([slate]) == run([slate])
    result = run([slate])
    assert result.straight_bets == 1
    assert result.ending_bankroll == Decimal("204.800")
    assert result.realized_pnl == Decimal("4.800")
    assert result.turnover == Decimal("4.00")
    assert result.maximum_drawdown == 0
    with pytest.raises(ValueError, match="must not be available"):
        run([replace(slate, outcomes=(replace(outcome, known_at=NOW),))])


def _qualified(opportunity: PricingOpportunity):
    return evaluate_candidate(_quote(opportunity, fair=opportunity.final_fair_probability), opportunity, QualificationPolicy(), as_of=NOW)


def _snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot("p", date(2026, 9, 5), Decimal("200"), Decimal("200"), Decimal(0), Decimal("200"), Decimal("200"), Decimal(0))


def _quote(opportunity: PricingOpportunity, *, fair: Decimal | None = None) -> FairValueQuote:
    return FairValueQuote(
        canonical_event_id=opportunity.event_id,
        model_id=f"ncaaf-market-consensus-{opportunity.market_type}-v1",
        model_version="1.0.0",
        model_status=ModelStatus.RETAINED_BENCHMARK,
        market_type=opportunity.market_type,
        selection_side=opportunity.selection_side,
        fair_probability=fair or opportunity.final_fair_probability,
        fair_point=opportunity.point,
        push_probability=None if opportunity.market_type == "moneyline" else Decimal(0),
        uncertainty_quality={"uncertainty": "low"},
        source_as_of=NOW,
        source_books=("draftkings", "fanduel", "betmgm"),
        source_book_count=3,
        consensus_dispersion=Decimal("0.01"),
        provenance={"registry_entry_hash": "x"},
    )


def _opportunity(
    *,
    event_id: UUID | None = None,
    market: str = "moneyline",
    side: str = "home",
    point: Decimal | None = None,
    odds: int = 110,
    fair: Decimal = Decimal("0.55"),
    home: str = "Team A",
    away: str = "Team B",
) -> PricingOpportunity:
    if market != "moneyline" and point is None:
        point = Decimal("52.5") if market == "total" else Decimal("-3.5")
    observations = tuple((uuid4(), uuid4(), uuid4()) for _ in range(3))
    books = tuple(
        BookNoVigPrice(
            key,
            name,
            fair,
            Decimal(1) - fair,
            Decimal("1.05"),
            Decimal("0.05"),
            selected,
            opposing,
            (snapshot,),
            odds,
            point,
            NOW,
        )
        for (key, name), (selected, opposing, snapshot) in zip(
            (("draftkings", "DraftKings"), ("fanduel", "FanDuel"), ("betmgm", "BetMGM")),
            observations,
            strict=True,
        )
    )
    observation, opposing, snapshot = observations[0]
    return PricingOpportunity(
        event_id=event_id or uuid4(), league="NCAAF", home_team=home, away_team=away,
        scheduled_start_utc=NOW + timedelta(hours=8), market_type=market, period="full_game",
        selection_side=side, selection_name=home if side == "home" else side.title(), point=point,
        best_sportsbook_key="draftkings", best_sportsbook_name="DraftKings", best_american_odds=odds,
        best_decimal_odds=american_odds_to_decimal(odds), raw_implied_probability=Decimal(100) / Decimal(odds + 100),
        no_vig_consensus_probability=fair, proprietary_model_probability=None,
        final_fair_probability_source="market_consensus", final_fair_probability=fair,
        probability_edge=fair - Decimal(100) / Decimal(odds + 100),
        ev_per_unit=fair * american_odds_to_decimal(odds) - Decimal(1), books_contributing=3,
        consensus_dispersion=Decimal("0.01"), uncertainty_indicator="low", outlier_sportsbooks=(),
        quality_warnings=(), vig_removal_policy_version="proportional-v1",
        consensus_policy_version="unweighted-median-v1", pricing_policy_version="market-baseline-v1",
        qualification_policy_version="baseline-qualification-v1",
        source_observation_ids=tuple(value for pair in observations for value in pair[:2]),
        best_executable_observation_id=observation,
        snapshot_ids=tuple(value[2] for value in observations),
        book_probabilities=books,
        calculated_at=NOW,
    )
