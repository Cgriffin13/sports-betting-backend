from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from app.domain.portfolio_engine import (
    ParlayOffer,
    ParlayPolicy,
    QualificationPolicy,
    RiskPolicy,
    construct_portfolio,
    evaluate_candidate,
)
from app.domain.recommendation_timing import classify_recommendation_timing
from app.domain.watchlist import build_watchlist
from tests.test_portfolio_engine import NOW, _opportunity, _quote, _snapshot


def test_watchlist_is_non_actionable_stakeless_and_deterministic() -> None:
    policy = QualificationPolicy()
    near = _opportunity(odds=100, fair=Decimal("0.507"), home="Near", away="Line")
    far = _opportunity(odds=100, fair=Decimal("0.501"), home="Far", away="Line")
    candidates = [
        evaluate_candidate(_quote(item, fair=item.final_fair_probability), item, policy, as_of=NOW)
        for item in (far, near)
    ]
    timing = classify_recommendation_timing(NOW, near.scheduled_start_utc)
    first = build_watchlist(candidates, policy, as_of=NOW, timing=timing)
    second = build_watchlist(tuple(reversed(candidates)), policy, as_of=NOW, timing=timing)

    assert first == second
    assert [item["home_team"] for item in first] == ["Near"]
    assert all(item["actionable"] is False for item in first)
    assert all("stake" not in item for item in first)
    assert first[0]["distance_to_qualification"] < 0.2
    assert (
        first[0]["market_probability_policy_version"]
        == near.market_probability_policy_version
    )


def test_exact_qualification_watchlist_and_pass_boundaries() -> None:
    policy = QualificationPolicy()
    candidate_a = _opportunity(odds=100, fair=Decimal("0.508"), home="A", away="Line")
    b_implied = Decimal(133) / Decimal(233)
    candidate_b = _opportunity(odds=-133, fair=b_implied + Decimal("0.008"), home="B", away="Line")
    c_implied = Decimal(100) / Decimal(229)
    candidate_c = _opportunity(odds=129, fair=c_implied + Decimal("0.007"), home="C", away="Line")
    candidate_d = _opportunity(odds=100, fair=Decimal("0.49"), home="D", away="Line")
    evaluations = [
        evaluate_candidate(_quote(item, fair=item.final_fair_probability), item, policy, as_of=NOW)
        for item in (candidate_a, candidate_b, candidate_c, candidate_d)
    ]

    watchlist = build_watchlist(
        evaluations,
        policy,
        as_of=NOW,
        timing=classify_recommendation_timing(NOW, candidate_a.scheduled_start_utc),
    )

    assert evaluations[0].qualified is True
    assert evaluations[0].ev_per_unit == Decimal("0.016")
    assert evaluations[0].edge == Decimal("0.008")
    assert evaluations[1].qualified is False
    assert Decimal("0.014") < evaluations[1].ev_per_unit < Decimal("0.0141")
    assert evaluations[1].edge.quantize(Decimal("0.000001")) == Decimal("0.008000")
    assert evaluations[2].qualified is False
    assert evaluations[2].ev_per_unit.quantize(Decimal("0.000001")) == Decimal("0.016030")
    assert evaluations[2].edge == Decimal("0.007")
    assert evaluations[3].ev_per_unit < 0
    assert {item["home_team"] for item in watchlist} == {"B", "C"}
    assert all(item["actionable"] is False and "stake" not in item for item in watchlist)


def test_qualified_and_structurally_invalid_candidates_do_not_enter_watchlist() -> None:
    policy = QualificationPolicy()
    qualified = _opportunity(odds=120, fair=Decimal("0.55"))
    mismatched_quote = replace(_quote(qualified), fair_point=Decimal("1"))
    items = build_watchlist(
        [
            evaluate_candidate(_quote(qualified), qualified, policy, as_of=NOW),
            evaluate_candidate(mismatched_quote, qualified, policy, as_of=NOW),
        ],
        policy,
        as_of=NOW,
        timing=classify_recommendation_timing(NOW, qualified.scheduled_start_utc),
    )
    assert items == []


def test_watchlist_excludes_started_games() -> None:
    policy = QualificationPolicy()
    near = replace(
        _opportunity(odds=100, fair=Decimal("0.507")),
        scheduled_start_utc=NOW - timedelta(minutes=1),
    )
    evaluation = evaluate_candidate(_quote(near), near, policy, as_of=NOW)
    assert build_watchlist(
        [evaluation],
        policy,
        as_of=NOW,
        timing=classify_recommendation_timing(NOW, NOW + timedelta(hours=1)),
    ) == []


def test_watchlist_candidate_cannot_enter_parlay_optimizer() -> None:
    policy = QualificationPolicy()
    near = _opportunity(odds=100, fair=Decimal("0.507"), home="Near", away="Line")
    evaluation = evaluate_candidate(_quote(near), near, policy, as_of=NOW)
    assert build_watchlist(
        [evaluation],
        policy,
        as_of=NOW,
        timing=classify_recommendation_timing(NOW, near.scheduled_start_utc),
    )
    offer = ParlayOffer(
        offer_id="watchlist-only",
        sportsbook_key="draftkings",
        leg_candidate_ids=(evaluation.candidate_id,),
        leg_observation_ids=(str(near.best_executable_observation_id),),
        american_odds=200,
        observed_at=NOW,
        provenance={"verified_provider_quote": True, "source_snapshot_id": "snapshot"},
    )

    decision = construct_portfolio(
        [evaluation],
        _snapshot(),
        top_n=10,
        risk_policy=RiskPolicy(),
        qualification_policy=policy,
        parlay_policy=ParlayPolicy(),
        parlay_offers=(offer,),
    )

    assert decision.straight_recommendations == ()
    assert decision.parlay is None


def test_extreme_longshot_is_research_visible_but_not_watchlist_or_actionable() -> None:
    policy = QualificationPolicy()
    opportunity = _opportunity(odds=1000, fair=Decimal("0.13"), home="Longshot", away="Favorite")
    evaluation = evaluate_candidate(_quote(opportunity), opportunity, policy, as_of=NOW)

    assert evaluation.ev_per_unit > 0
    assert evaluation.edge > 0
    assert evaluation.rejection_reasons == ("outside_main_board_odds_profile",)
    assert build_watchlist(
        [evaluation],
        policy,
        as_of=NOW,
        timing=classify_recommendation_timing(NOW, opportunity.scheduled_start_utc),
    ) == []

    decision = construct_portfolio(
        [evaluation],
        _snapshot(),
        top_n=10,
        risk_policy=RiskPolicy(),
        qualification_policy=policy,
        parlay_policy=ParlayPolicy(),
    )
    assert decision.evaluated_candidates == (evaluation,)
    assert decision.straight_recommendations == ()
    assert decision.parlay is None
