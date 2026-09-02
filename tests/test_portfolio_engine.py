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
    expected_log_growth,
    fractional_kelly_with_push,
    optimize_parlay,
    portfolio_state,
)
from app.domain.pricing import (
    BookNoVigPrice,
    PricingOpportunity,
    american_odds_to_decimal,
    american_odds_to_implied_probability,
)
from app.domain.portfolio_simulator import SimulationOutcome, SimulationSlate, simulate_portfolio

NOW = datetime(2026, 9, 5, 13, tzinfo=UTC)


def test_push_aware_ev_and_fractional_kelly_math() -> None:
    fraction = fractional_kelly_with_push(Decimal("0.55"), Decimal("0.05"), Decimal("2.0"))
    assert fraction == Decimal("0.1578947368421052631578947368")
    assert fraction > 0
    assert RiskPolicy().kelly_fraction == Decimal("0.25")
    assert QualificationPolicy().maximum_actionable_positive_american_odds == 500
    with pytest.raises(ValueError, match="Full Kelly"):
        RiskPolicy(kelly_fraction=Decimal(1))
    with pytest.raises(ValueError, match=r"at least \+100"):
        QualificationPolicy(maximum_actionable_positive_american_odds=99)


def test_expected_log_growth_is_push_aware_and_numerically_safe() -> None:
    growth = expected_log_growth(
        Decimal("0.55"),
        Decimal("0.05"),
        Decimal("2.0"),
        Decimal("0.01"),
    )
    expected = Decimal("0.55") * Decimal("1.01").ln() + Decimal("0.40") * Decimal("0.99").ln()
    assert growth == expected
    assert expected_log_growth(Decimal("0.55"), Decimal(0), Decimal("2.0"), Decimal(0)) == 0
    with pytest.raises(ValueError, match="between zero and one"):
        expected_log_growth(Decimal("0.55"), Decimal(0), Decimal("2.0"), Decimal(1))


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


def test_risk_adjusted_ranking_and_main_board_guardrail_prefer_standard_juice() -> None:
    longshots = (
        _qualified(
            _opportunity(
                odds=1000,
                fair=Decimal("0.10"),
                home="Longshot One",
                away="Favorite One",
            )
        ),
        _qualified(
            _opportunity(
                odds=2000,
                fair=Decimal("0.06"),
                home="Longshot Two",
                away="Favorite Two",
            )
        ),
    )
    standard_juice = _qualified(
        _opportunity(
            market="spread",
            side="home",
            point=Decimal("-3.5"),
            odds=-110,
            fair=Decimal("0.55"),
            home="Balanced State",
            away="Peer University",
        )
    )

    assert all(longshot.ev_per_unit > standard_juice.ev_per_unit for longshot in longshots)
    decision = construct_portfolio(
        [*longshots, standard_juice],
        _snapshot(),
        top_n=1,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    )
    repeated = construct_portfolio(
        [standard_juice, *reversed(longshots)],
        _snapshot(),
        top_n=1,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    )

    selected = decision.straight_recommendations[0]
    assert selected.candidate.candidate_id == standard_juice.candidate_id
    assert repeated.decision_hash == decision.decision_hash
    assert all(not item.qualified for item in longshots)
    assert all("outside_main_board_odds_profile" in item.rejection_reasons for item in longshots)

    # The mathematical ranking correction is independently sufficient for these
    # realistic weak longshots: at quarter Kelly their expected log growth is
    # below the standard-juice spread even before the +500 safety guardrail.
    standard_fraction = fractional_kelly_with_push(
        standard_juice.win_probability,
        standard_juice.push_probability,
        standard_juice.opportunity.best_decimal_odds,
    ) * RiskPolicy().kelly_fraction
    standard_growth = expected_log_growth(
        standard_juice.win_probability,
        standard_juice.push_probability,
        standard_juice.opportunity.best_decimal_odds,
        standard_fraction,
    )
    longshot_growth = tuple(
        expected_log_growth(
            item.win_probability,
            item.push_probability,
            item.opportunity.best_decimal_odds,
            fractional_kelly_with_push(
                item.win_probability,
                item.push_probability,
                item.opportunity.best_decimal_odds,
            )
            * RiskPolicy().kelly_fraction
            * RiskPolicy().opportunistic_multiplier,
        )
        for item in longshots
    )
    assert standard_growth > max(longshot_growth)


def test_main_board_guardrail_keeps_extreme_longshot_calculable_but_non_actionable() -> None:
    longshot = _qualified(_opportunity(odds=1000, fair=Decimal("0.13")))
    decision = construct_portfolio(
        [longshot],
        _snapshot(),
        top_n=10,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    )
    assert longshot.ev_per_unit == Decimal("0.43")
    assert longshot.edge > 0
    assert not longshot.qualified
    assert longshot.rejection_reasons == ("outside_main_board_odds_profile",)
    assert decision.straight_recommendations == ()
    assert decision.parlay is None


def test_positive_500_boundary_remains_growth_ranked_but_501_is_diagnostic_only() -> None:
    at_boundary = _qualified(
        _opportunity(odds=500, fair=Decimal("0.20"), home="Boundary", away="Peer")
    )
    outside = _qualified(
        _opportunity(odds=501, fair=Decimal("0.20"), home="Outside", away="Other")
    )

    assert at_boundary.qualified
    assert at_boundary.classification == PositionClass.CORE
    assert not outside.qualified
    assert outside.ev_per_unit > 0
    assert outside.rejection_reasons == ("outside_main_board_odds_profile",)

    decision = construct_portfolio(
        [outside, at_boundary],
        _snapshot(),
        top_n=10,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
        parlay_offers=(
            ParlayOffer(
                "guardrail-parlay",
                "draftkings",
                (at_boundary.candidate_id, outside.candidate_id),
                (
                    str(at_boundary.opportunity.best_executable_observation_id),
                    str(outside.opportunity.best_executable_observation_id),
                ),
                1200,
                NOW,
                {"verified_provider_quote": True, "source_snapshot_id": "snapshot"},
            ),
        ),
    )
    assert [item.candidate.candidate_id for item in decision.straight_recommendations] == [
        at_boundary.candidate_id
    ]
    assert decision.parlay is None


def test_main_board_guardrail_is_not_a_negative_odds_band_or_primary_ranker() -> None:
    strong_favorite = _qualified(_opportunity(odds=-400, fair=Decimal("0.84")))
    moderate = _qualified(_opportunity(odds=400, fair=Decimal("0.23")))

    assert strong_favorite.qualified
    assert moderate.qualified
    decision = construct_portfolio(
        [moderate, strong_favorite],
        _snapshot(),
        top_n=10,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    )
    assert len(decision.straight_recommendations) == 2
    assert all(item.candidate.ranking_score > 0 for item in decision.straight_recommendations)


def test_consensus_outlier_warning_is_informational_but_dispersion_still_fails_closed() -> None:
    opportunity = replace(
        _opportunity(odds=120, fair=Decimal("0.55")),
        consensus_dispersion=Decimal("0.04"),
        outlier_sportsbooks=("draftkings",),
        quality_warnings=("material_book_outlier", "best_executable_book_outlier"),
    )
    quote = replace(_quote(opportunity), consensus_dispersion=Decimal("0.04"))
    evaluation = evaluate_candidate(quote, opportunity, QualificationPolicy(), as_of=NOW)
    assert evaluation.qualified
    assert evaluation.quote_integrity == "verified_best_price_consensus_outlier"

    excessive = replace(_quote(opportunity), consensus_dispersion=Decimal("0.061"))
    rejected = evaluate_candidate(excessive, opportunity, QualificationPolicy(), as_of=NOW)
    assert not rejected.qualified
    assert "excessive_or_unknown_dispersion" in rejected.rejection_reasons


def test_robust_growth_uses_least_favorable_contributing_probability() -> None:
    stable_opportunity = _opportunity(
        odds=120,
        fair=Decimal("0.55"),
        home="Stable",
        away="Peer Stable",
    )
    fragile_books = (
        replace(
            stable_opportunity.book_probabilities[0],
            selection_probability=Decimal("0.50"),
            opposing_probability=Decimal("0.50"),
        ),
        *stable_opportunity.book_probabilities[1:],
    )
    fragile_opportunity = replace(
        stable_opportunity,
        event_id=uuid4(),
        home_team="Fragile",
        away_team="Peer Fragile",
        book_probabilities=fragile_books,
        consensus_dispersion=Decimal("0.05"),
        outlier_sportsbooks=("draftkings",),
        quality_warnings=("material_book_outlier", "best_executable_book_outlier"),
    )
    stable = evaluate_candidate(
        _quote(stable_opportunity),
        stable_opportunity,
        QualificationPolicy(),
        as_of=NOW,
    )
    fragile = evaluate_candidate(
        replace(_quote(fragile_opportunity), consensus_dispersion=Decimal("0.05")),
        fragile_opportunity,
        QualificationPolicy(),
        as_of=NOW,
    )
    decision = construct_portfolio(
        [fragile, stable],
        _snapshot(),
        top_n=2,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    )
    ranked = {item.candidate_id: item for item in decision.evaluated_candidates}
    assert stable.qualified and fragile.qualified
    assert ranked[stable.candidate_id].expected_log_growth == ranked[fragile.candidate_id].expected_log_growth
    assert (
        ranked[stable.candidate_id].robust_expected_log_growth
        > ranked[fragile.candidate_id].robust_expected_log_growth
    )


def test_unknown_pricing_warning_remains_a_hard_rejection() -> None:
    opportunity = replace(
        _opportunity(odds=120, fair=Decimal("0.55")),
        quality_warnings=("malformed_executable_quote",),
    )
    rejected = evaluate_candidate(_quote(opportunity), opportunity, QualificationPolicy(), as_of=NOW)
    assert "pricing_quality_warning" in rejected.rejection_reasons


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


def test_parlay_ranking_uses_expected_growth_before_raw_joint_ev() -> None:
    risk = RiskPolicy(
        maximum_daily_fraction=Decimal("0.20"),
        maximum_market_fraction=Decimal("0.20"),
    )
    snapshot = replace(
        _snapshot(),
        starting_bankroll=Decimal("1000"),
        cash=Decimal("1000"),
        equity=Decimal("1000"),
        peak_equity=Decimal("1000"),
    )
    opportunities = (
        _opportunity(odds=500, fair=Decimal("0.20"), home="L1", away="L2"),
        _opportunity(odds=500, fair=Decimal("0.20"), home="L3", away="L4"),
        _opportunity(odds=-150, fair=Decimal("0.70"), home="M1", away="M2"),
        _opportunity(odds=-150, fair=Decimal("0.70"), home="M3", away="M4"),
    )
    straight = construct_portfolio(
        [_qualified(item) for item in opportunities],
        snapshot,
        top_n=10,
        risk_policy=risk,
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    ).straight_recommendations
    by_home = {item.candidate.opportunity.home_team: item for item in straight}

    def offer(offer_id: str, homes: tuple[str, str], odds: int) -> ParlayOffer:
        legs = tuple(by_home[home] for home in homes)
        return ParlayOffer(
            offer_id,
            "draftkings",
            tuple(item.candidate.candidate_id for item in legs),
            tuple(str(item.candidate.opportunity.best_executable_observation_id) for item in legs),
            odds,
            NOW,
            {"verified_provider_quote": True, "source_snapshot_id": "snapshot"},
        )

    longshot_offer = offer("longshot", ("L1", "L3"), 4000)
    moderate_offer = offer("moderate", ("M1", "M3"), 150)
    parlay, reason = optimize_parlay(
        straight,
        [longshot_offer, moderate_offer],
        snapshot,
        state=PortfolioState.NORMAL,
        risk_policy=risk,
        policy=ParlayPolicy(),
    )

    assert reason == "selected"
    assert parlay is not None
    assert Decimal("0.64") > Decimal("0.225")  # longshot raw joint EV is larger
    assert parlay.offer.offer_id == "moderate"


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
        best_decimal_odds=american_odds_to_decimal(odds),
        raw_implied_probability=american_odds_to_implied_probability(odds),
        no_vig_consensus_probability=fair, proprietary_model_probability=None,
        final_fair_probability_source="market_consensus", final_fair_probability=fair,
        probability_edge=fair - american_odds_to_implied_probability(odds),
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
