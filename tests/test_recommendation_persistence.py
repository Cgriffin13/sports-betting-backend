from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from app.api import recommendations as recommendations_api
from app.db.market_models import CanonicalEvent
from app.db.models import Bet, BetApproval, LedgerEntry, Recommendation
from app.db.portfolio_models import RecommendationDecisionRun, RecommendationLeg
from app.domain.identity import Principal
from app.domain.errors import RecommendationStateError
from app.domain.portfolio_engine import ParlayOffer, ParlayPolicy, QualificationPolicy, RiskPolicy, construct_portfolio
from app.persistence.recommendation_repository import SqlAlchemyRecommendationRepository
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.security import ApiKeyAuthenticator
from app.services.portfolio_service import PortfolioService
from tests.test_portfolio_engine import NOW, _qualified, _opportunity


def test_phase6_schema_compiles_for_postgresql() -> None:
    for model in (RecommendationDecisionRun, RecommendationLeg, Recommendation, Bet):
        sql = str(CreateTable(cast(Table, model.__table__)).compile(dialect=postgresql.dialect()))
        assert "JSONB" in sql


def test_persist_approve_and_settle_recommendation_use_one_ledger(
    session_factory: sessionmaker[Session],
) -> None:
    principal = Principal("owner-primary", "Primary Owner")
    repository = SqlAlchemyRecommendationRepository(session_factory, Decimal("200"))
    opportunity = _opportunity(odds=120, fair=Decimal("0.55"))
    _event(session_factory, opportunity.event_id, opportunity.home_team, opportunity.away_team)
    snapshot = repository.portfolio_snapshot(principal, "main", date(2026, 9, 5))
    decision = construct_portfolio(
        [_qualified(opportunity)], snapshot, top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )

    first = repository.persist_decision(
        principal, snapshot, decision, as_of=NOW, input_hash="a" * 64,
        pricing_rejections={}, top_n=10,
    )
    repeated = repository.persist_decision(
        principal, snapshot, decision, as_of=NOW, input_hash="a" * 64,
        pricing_rejections={}, top_n=10,
    )
    assert first == repeated
    serialized = first["straight_recommendations"][0]
    assert "market-consensus opportunity" in serialized["explanation"]
    assert len(serialized["executable_alternatives"]) == 3
    recommendation_id = first["straight_recommendations"][0]["recommendation_id"]
    approved = repository.approve(principal, recommendation_id, idempotency_key="approval-1")
    assert approved["bankroll_after"] == 196.0
    assert repository.approve(principal, recommendation_id, idempotency_key="approval-1")["bet_id"] == approved["bet_id"]

    with session_factory() as session:
        recommendation = session.scalar(select(Recommendation).where(Recommendation.external_id == recommendation_id))
        bet = session.scalar(select(Bet).where(Bet.external_id == approved["bet_id"]))
        assert recommendation is not None and recommendation.status == "approved"
        assert bet is not None and bet.recommendation_hash == recommendation.recommendation_hash
        assert bet.canonical_event_id == opportunity.event_id
        approval = session.scalar(select(BetApproval).where(BetApproval.bet_id == bet.id))
        assert approval is not None and approval.recommendation_id == recommendation.id
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 2

    portfolio_service = PortfolioService(SqlAlchemyPortfolioRepository(session_factory, Decimal("200")))
    portfolio_service.settle_bet(
        principal,
        {"portfolio_id": "main", "bet_id": approved["bet_id"], "result": "win", "payout": Decimal("4.80")},
        idempotency_key="settle-1",
    )
    stats = portfolio_service.get_stats(principal, "main")
    assert stats["equity"] == 204.8
    assert stats["attribution"]["classification"]["CORE"]["pnl"] == 4.8
    assert stats["attribution"]["bet_kind"]["straight"]["bets"] == 1


def test_persistence_and_upcoming_api_order_preserve_portfolio_ranking(
    session_factory: sessionmaker[Session],
) -> None:
    principal = Principal("owner-primary", "Primary Owner")
    repository = SqlAlchemyRecommendationRepository(session_factory, Decimal("200"))
    lower = _opportunity(odds=120, fair=Decimal("0.55"), home="Lower", away="Peer A")
    higher = _opportunity(odds=120, fair=Decimal("0.60"), home="Higher", away="Peer B")
    for item in (lower, higher):
        _event(session_factory, item.event_id, item.home_team, item.away_team)
    snapshot = repository.portfolio_snapshot(principal, "main", date(2026, 9, 5))
    decision = construct_portfolio(
        [_qualified(lower), _qualified(higher)],
        snapshot,
        top_n=10,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    )

    persisted = repository.persist_decision(
        principal,
        snapshot,
        decision,
        as_of=NOW,
        input_hash="r" * 64,
        pricing_rejections={},
        top_n=10,
    )
    straight = persisted["straight_recommendations"]
    assert [item["selection"] for item in straight] == ["Higher", "Lower"]
    assert [item["portfolio_rank"] for item in straight] == [1, 2]
    assert straight[0]["ranking_score"] > straight[1]["ranking_score"]
    assert straight[0]["raw_kelly_fraction"] is not None
    assert straight[0]["adjusted_kelly_fraction"] is not None
    assert straight[0]["quote_integrity"] == "verified"

    listed = repository.list_recommendations(principal, "main", upcoming_as_of=NOW)
    assert [item["recommendation_id"] for item in listed] == [
        item["recommendation_id"] for item in straight
    ]


def test_latest_watchlist_state_promotes_without_becoming_actionable(
    session_factory: sessionmaker[Session],
) -> None:
    principal = Principal("owner-primary", "Primary Owner")
    repository = SqlAlchemyRecommendationRepository(session_factory, Decimal("200"))
    opportunity = _opportunity(odds=120, fair=Decimal("0.55"))
    _event(session_factory, opportunity.event_id, opportunity.home_team, opportunity.away_team)
    snapshot = repository.portfolio_snapshot(principal, "main", date(2026, 9, 5))
    qualified = construct_portfolio(
        [_qualified(opportunity)], snapshot, top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )
    watchlist_item = {
        "watchlist_id": "candidate-1", "event_id": str(opportunity.event_id),
        "slate_date": "2026-09-05", "scheduled_start": opportunity.scheduled_start_utc.isoformat(),
        "home_team": opportunity.home_team, "away_team": opportunity.away_team,
        "market": "moneyline", "side": "home", "selection": opportunity.selection_name,
        "sportsbook": "draftkings", "point": None, "odds": 100,
        "fair_probability": 0.507, "implied_probability": 0.5, "edge": 0.007,
        "ev_per_unit": 0.014, "books_count": 3, "dispersion": 0.01,
        "freshness_age_seconds": 0, "fresh": True, "timing_classification": "EARLY_LOOKAHEAD",
        "primary_horizon_at": NOW.isoformat(), "rejection_reasons": ["below_minimum_ev"],
        "primary_blocker": "below_minimum_ev", "failed_gate_count": 1,
        "distance_to_qualification": 0.0666666667, "ranking_score": 0.9375,
        "source_observation_ids": [], "snapshot_ids": [],
        "best_executable_observation_id": str(opportunity.best_executable_observation_id),
        "watchlist_version": "ncaaf-watchlist-v1", "actionable": False,
    }
    repository.persist_decision(
        principal, snapshot, replace(qualified, straight_recommendations=()), as_of=NOW,
        input_hash="w" * 64, pricing_rejections={}, top_n=10, watchlist=[watchlist_item],
        analysis_summary={"games_analyzed": 1, "watchlist_markets": 1},
    )
    first = repository.list_watchlist(principal, "main", as_of=NOW)
    assert first["upcoming_games_analyzed"] == 1
    assert first["watchlist_count"] == 1
    assert first["items"][0]["actionable"] is False

    repository.persist_decision(
        principal, snapshot, qualified, as_of=NOW + timedelta(minutes=1),
        input_hash="q" * 64, pricing_rejections={}, top_n=10, watchlist=[],
        analysis_summary={"games_analyzed": 1, "watchlist_markets": 0},
    )
    promoted = repository.list_watchlist(principal, "main", as_of=NOW + timedelta(minutes=1))
    assert promoted["watchlist_count"] == 0
    assert promoted["qualified_recommendations"] == 1


def test_watchlist_api_serializes_legacy_and_current_policy_provenance(
    session_factory: sessionmaker[Session],
) -> None:
    principal = Principal("owner-primary", "Primary Owner")
    repository = SqlAlchemyRecommendationRepository(session_factory, Decimal("200"))
    opportunity = _opportunity(odds=120, fair=Decimal("0.55"))
    _event(session_factory, opportunity.event_id, opportunity.home_team, opportunity.away_team)
    snapshot = repository.portfolio_snapshot(principal, "main", date(2026, 9, 5))
    decision = construct_portfolio(
        [_qualified(opportunity)], snapshot, top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )
    legacy_item = {
        "watchlist_id": "legacy-candidate", "event_id": str(opportunity.event_id),
        "slate_date": "2026-09-05", "scheduled_start": opportunity.scheduled_start_utc.isoformat(),
        "home_team": opportunity.home_team, "away_team": opportunity.away_team,
        "market": "moneyline", "side": "home", "selection": opportunity.selection_name,
        "sportsbook": "draftkings", "point": None, "odds": 100,
        "fair_probability": 0.507, "implied_probability": 0.5, "edge": 0.007,
        "ev_per_unit": 0.014, "books_count": 3, "dispersion": 0.01,
        "freshness_age_seconds": 0, "fresh": True, "timing_classification": "EARLY_LOOKAHEAD",
        "primary_horizon_at": NOW.isoformat(), "rejection_reasons": ["below_minimum_ev"],
        "primary_blocker": "below_minimum_ev", "failed_gate_count": 1,
        "distance_to_qualification": 0.0666666667, "ranking_score": 0.9375,
        "source_observation_ids": [], "snapshot_ids": [],
        "best_executable_observation_id": str(opportunity.best_executable_observation_id),
        "watchlist_version": "ncaaf-watchlist-v1", "actionable": False,
    }
    current_item = {
        **legacy_item,
        "watchlist_id": "current-candidate",
        "market_probability_policy_version": "ncaaf-market-probability-v1",
    }
    repository.persist_decision(
        principal,
        snapshot,
        replace(decision, straight_recommendations=()),
        as_of=NOW,
        input_hash="l" * 64,
        pricing_rejections={},
        top_n=10,
        watchlist=[legacy_item, current_item],
        analysis_summary={"games_analyzed": 1, "watchlist_markets": 2},
    )

    application = FastAPI()
    application.state.authenticator = ApiKeyAuthenticator({"watchlist-key": principal})
    application.state.clock = lambda: NOW
    application.state.recommendation_service = SimpleNamespace(
        watchlist=lambda owner, portfolio_id, *, as_of: repository.list_watchlist(
            owner, portfolio_id, as_of=as_of
        )
    )
    application.include_router(recommendations_api.router)

    response = TestClient(application).get(
        "/portfolio/main/watchlist",
        params={"upcoming_only": True},
        headers={"X-API-Key": "watchlist-key"},
    )

    assert response.status_code == 200, response.text
    items = {item["watchlist_id"]: item for item in response.json()["items"]}
    assert items["legacy-candidate"]["market_probability_policy_version"] is None
    assert (
        items["current-candidate"]["market_probability_policy_version"]
        == "ncaaf-market-probability-v1"
    )


def test_risk_snapshot_counts_open_recommended_exposure(
    session_factory: sessionmaker[Session],
) -> None:
    principal = Principal("owner-primary", "Primary Owner")
    repository = SqlAlchemyRecommendationRepository(session_factory, Decimal("200"))
    opportunity = _opportunity(odds=120, fair=Decimal("0.55"))
    _event(session_factory, opportunity.event_id, opportunity.home_team, opportunity.away_team)
    snapshot = repository.portfolio_snapshot(principal, "main", date(2026, 9, 5))
    decision = construct_portfolio(
        [_qualified(opportunity)], snapshot, top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
    )
    run = repository.persist_decision(principal, snapshot, decision, as_of=NOW, input_hash="b" * 64, pricing_rejections={}, top_n=10)
    repository.approve(principal, run["straight_recommendations"][0]["recommendation_id"], idempotency_key=None)

    risk = repository.risk_summary(principal, "main", date(2026, 9, 5))
    assert risk["reserved_exposure"] == 4.0
    assert risk["by_game"][str(opportunity.event_id)] == 4.0
    assert risk["by_team"][opportunity.home_team] == 4.0


def test_parlay_approval_and_settlement_share_the_portfolio_ledger(
    session_factory: sessionmaker[Session],
) -> None:
    principal = Principal("owner-primary", "Primary Owner")
    repository = SqlAlchemyRecommendationRepository(session_factory, Decimal("200"))
    first = _opportunity(odds=150, fair=Decimal("0.55"), home="A", away="B")
    second = _opportunity(odds=140, fair=Decimal("0.54"), home="C", away="D")
    for item in (first, second):
        _event(session_factory, item.event_id, item.home_team, item.away_team)
    candidates = [_qualified(first), _qualified(second)]
    provisional = construct_portfolio(
        candidates,
        repository.portfolio_snapshot(principal, "main", date(2026, 9, 5)),
        top_n=10,
        risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(),
        parlay_policy=ParlayPolicy(),
    )
    offer = ParlayOffer(
        "verified-quote",
        "draftkings",
        tuple(item.candidate.candidate_id for item in provisional.straight_recommendations),
        tuple(str(item.candidate.opportunity.best_executable_observation_id) for item in provisional.straight_recommendations),
        500,
        NOW,
        {"verified_provider_quote": True, "source_snapshot_id": "snapshot"},
    )
    snapshot = repository.portfolio_snapshot(principal, "main", date(2026, 9, 5))
    decision = construct_portfolio(
        candidates, snapshot, top_n=10, risk_policy=RiskPolicy(),
        qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(), parlay_offers=(offer,),
    )
    assert decision.parlay is not None
    run = repository.persist_decision(principal, snapshot, decision, as_of=NOW, input_hash="c" * 64, pricing_rejections={}, top_n=10)
    parlay = run["parlay_of_the_day"]
    assert len(parlay["legs"]) == 2
    assert parlay["confidence_quality"]["correlation_method"] == "cross-event-disjoint-team-independence-v1"
    assert parlay["confidence_quality"]["gross_payout_if_win"] == "6.00"
    assert parlay["confidence_quality"]["incremental_exposure"]
    approved = repository.approve(principal, parlay["recommendation_id"], idempotency_key="parlay-1")

    service = PortfolioService(SqlAlchemyPortfolioRepository(session_factory, Decimal("200")))
    service.settle_bet(
        principal,
        {"portfolio_id": "main", "bet_id": approved["bet_id"], "result": "win", "payout": Decimal("5")},
        idempotency_key="parlay-settle",
    )
    stats = service.get_stats(principal, "main")
    assert stats["attribution"]["bet_kind"]["parlay"]["pnl"] == 5.0
    assert stats["attribution"]["market"]["parlay"]["bets"] == 1


def test_approval_revalidates_current_exposure_after_decision(
    session_factory: sessionmaker[Session],
) -> None:
    principal = Principal("owner-primary", "Primary Owner")
    repository = SqlAlchemyRecommendationRepository(session_factory, Decimal("200"))
    opportunity = _opportunity(odds=200, fair=Decimal("0.60"))
    _event(session_factory, opportunity.event_id, opportunity.home_team, opportunity.away_team)
    recommendation_ids: list[str] = []
    for marker in ("d", "e", "f"):
        snapshot = repository.portfolio_snapshot(principal, "main", date(2026, 9, 5))
        decision = construct_portfolio(
            [_qualified(opportunity)], snapshot, top_n=10, risk_policy=RiskPolicy(),
            qualification_policy=QualificationPolicy(), parlay_policy=ParlayPolicy(),
        )
        run = repository.persist_decision(
            principal, snapshot, decision, as_of=NOW, input_hash=marker * 64,
            pricing_rejections={}, top_n=10,
        )
        recommendation_ids.append(run["straight_recommendations"][0]["recommendation_id"])
    repository.approve(principal, recommendation_ids[0], idempotency_key=None)
    repository.approve(principal, recommendation_ids[1], idempotency_key=None)
    with pytest.raises(RecommendationStateError, match="per-game"):
        repository.approve(principal, recommendation_ids[2], idempotency_key=None)


def _event(
    session_factory: sessionmaker[Session],
    event_id: object,
    home: str,
    away: str,
) -> None:
    with session_factory.begin() as session:
        session.add(
            CanonicalEvent(
                id=event_id,
                league="NCAAF",
                home_team=home,
                away_team=away,
                scheduled_start_utc=datetime(2026, 9, 5, 21, tzinfo=UTC),
                event_status="scheduled",
                match_confidence=Decimal(1),
                review_status="matched",
                match_provenance={"method": "test"},
                season=2026,
                week=1,
            )
        )
