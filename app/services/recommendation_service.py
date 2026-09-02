from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from app.domain.identity import Principal
from app.domain.model_registry import ConsensusFairValueInput, RegistryError, canonical_hash
from app.domain.portfolio_engine import (
    CandidateEvaluation,
    ParlayOffer,
    ParlayPolicy,
    QualifiedNonActionableOpportunity,
    QualificationPolicy,
    RiskPolicy,
    StraightRecommendation,
    construct_portfolio,
    evaluate_candidate,
)
from app.domain.recommendation_timing import classify_recommendation_timing
from app.domain.watchlist import build_watchlist
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.persistence.recommendation_repository import SqlAlchemyRecommendationRepository
from app.services.model_registry_service import FairValueService
from app.services.pricing_service import PricingService

RETAINED_MODELS = {
    "moneyline": "ncaaf-market-consensus-moneyline-v1",
    "spread": "ncaaf-market-consensus-spread-v1",
    "total": "ncaaf-market-consensus-total-v1",
}


class RecommendationService:
    def __init__(
        self,
        *,
        pricing_service: PricingService,
        registry_repository: SqlAlchemyModelRegistryRepository,
        repository: SqlAlchemyRecommendationRepository,
        qualification_policy: QualificationPolicy,
        risk_policy: RiskPolicy,
        parlay_policy: ParlayPolicy,
    ) -> None:
        self.pricing_service = pricing_service
        self.registry_repository = registry_repository
        self.repository = repository
        self.qualification_policy = qualification_policy
        self.risk_policy = risk_policy
        self.parlay_policy = parlay_policy
        self.fair_value_service = FairValueService()

    def analyze(
        self,
        principal: Principal,
        *,
        portfolio_id: str,
        slate_date: date,
        as_of: datetime,
        market_types: list[str],
        top_n: int,
        parlay_offers: Sequence[ParlayOffer] = (),
        games_received: int | None = None,
        observations_received: int | None = None,
    ) -> dict[str, Any]:
        pricing = self.pricing_service.analyze(
            leagues=["NCAAF"],
            market_types=market_types,
            as_of=as_of,
            event_date=slate_date,
            top_n=50,
        )
        evaluations = []
        rejection_counts: Counter[str] = Counter(pricing.rejection_counts)
        for opportunity in pricing.candidates:
            try:
                registration = self._registration(opportunity.market_type)
                quote = self.fair_value_service.quote(
                    registration,
                    ConsensusFairValueInput(
                        canonical_event_id=opportunity.event_id,
                        market_type=opportunity.market_type,
                        selection_side=opportunity.selection_side,
                        fair_probability=opportunity.final_fair_probability,
                        fair_point=opportunity.point,
                        push_probability=(
                            None
                            if opportunity.market_type == "moneyline"
                            else opportunity.push_probability
                        ),
                        as_of=pricing.as_of,
                        source_books=tuple(item.sportsbook_key for item in opportunity.book_probabilities),
                        consensus_dispersion=opportunity.consensus_dispersion,
                        quality_metadata={
                            "uncertainty": opportunity.uncertainty_indicator,
                            "quality_warnings": list(opportunity.quality_warnings),
                            "fresh": True,
                            "consensus_fair_point": (
                                str(opportunity.consensus_fair_point)
                                if opportunity.consensus_fair_point is not None
                                else None
                            ),
                            "line_advantage": (
                                str(opportunity.line_advantage)
                                if opportunity.line_advantage is not None
                                else None
                            ),
                            "center_dispersion": (
                                str(opportunity.center_dispersion)
                                if opportunity.center_dispersion is not None
                                else None
                            ),
                        },
                        provenance={
                            "pricing_policy_version": opportunity.pricing_policy_version,
                            "qualification_policy_version": opportunity.qualification_policy_version,
                            "source_observation_ids": [str(value) for value in opportunity.source_observation_ids],
                            "snapshot_ids": [str(value) for value in opportunity.snapshot_ids],
                            "best_executable_observation_id": str(opportunity.best_executable_observation_id),
                            "market_probability_policy_version": (
                                opportunity.market_probability_policy_version
                            ),
                            "market_curve_artifact_hash": opportunity.market_curve_artifact_hash,
                        },
                    ),
                )
                evaluation = evaluate_candidate(
                    quote,
                    opportunity,
                    self.qualification_policy,
                    as_of=as_of,
                )
                evaluations.append(evaluation)
                rejection_counts.update(
                    reason
                    for reason in evaluation.rejection_reasons
                    if reason not in opportunity.pricing_gate_failures
                )
            except RegistryError as exc:
                rejection_counts[f"fair_value_registry:{exc}"] += 1
        snapshot = self.repository.portfolio_snapshot(principal, portfolio_id, slate_date)
        verified_offers = tuple(
            offer
            for offer in parlay_offers
            if bool(offer.provenance.get("verified_provider_quote"))
            and bool(offer.provenance.get("source_snapshot_id"))
            and offer.observed_at <= as_of
            and (as_of - offer.observed_at).total_seconds()
            <= self.qualification_policy.maximum_market_age_seconds
        )
        decision = construct_portfolio(
            evaluations,
            snapshot,
            top_n=top_n,
            risk_policy=self.risk_policy,
            qualification_policy=self.qualification_policy,
            parlay_policy=self.parlay_policy,
            parlay_offers=verified_offers,
        )
        timing = (
            classify_recommendation_timing(as_of, pricing.first_scheduled_start_utc)
            if pricing.first_scheduled_start_utc is not None
            else None
        )
        watchlist = (
            build_watchlist(
                decision.evaluated_candidates,
                self.qualification_policy,
                as_of=as_of,
                timing=timing,
            )
            if timing is not None
            else []
        )
        qualified_candidates = sum(item.qualified for item in evaluations)
        qualified_opportunities = [
            _serialize_qualified_non_actionable(
                item,
                as_of=as_of,
                timing=timing,
                qualification_policy_version=self.qualification_policy.version,
                risk_policy_version=self.risk_policy.version,
            )
            for item in decision.qualified_non_actionable
        ]
        pricing_funnel = {
            **pricing.funnel,
            "games_received": games_received
            if games_received is not None
            else pricing.funnel["games_received"],
            "observations_received": observations_received
            if observations_received is not None
            else pricing.funnel["observations_received"],
            "watchlist_candidates": len(watchlist),
            "qualified_candidates": qualified_candidates,
            "actionable_candidates": len(decision.straight_recommendations),
            "pass_candidates": max(0, len(pricing.candidates) - qualified_candidates - len(watchlist)),
        }
        analysis_summary = {
            "games_analyzed": pricing.events_analyzed,
            "pricing_opportunities": pricing.opportunities_qualified,
            "candidates_evaluated": len(evaluations),
            "qualified_candidates": qualified_candidates,
            "actionable_straights": len(decision.straight_recommendations),
            # Retained for compatibility with refresh clients that historically
            # interpreted this field as actionable straight recommendations.
            "qualified_straights": len(decision.straight_recommendations),
            "qualified_non_actionable_count": len(qualified_opportunities),
            "qualified_opportunities": qualified_opportunities,
            "watchlist_markets": len(watchlist),
            "pricing_funnel": pricing_funnel,
            "rejection_counts": dict(sorted(rejection_counts.items())),
            "pricing_pipeline_status": pricing.pipeline_status,
            "pricing_pipeline_status_reason": pricing.pipeline_status_reason,
            "candidate_diagnostics": build_candidate_diagnostics(
                decision.evaluated_candidates,
                watchlist,
                decision.straight_recommendations,
            ),
        }
        input_hash = canonical_hash(
            {
                "portfolio_id": portfolio_id,
                "slate_date": slate_date,
                "as_of": as_of,
                "pricing_policy": pricing.pricing_policy_version,
                "qualification_policy": self.qualification_policy.version,
                "risk_policy": self.risk_policy.version,
                "parlay_policy": self.parlay_policy.version,
                "candidate_ids": [item.candidate_id for item in evaluations],
                "parlay_offer_ids": [item.offer_id for item in verified_offers],
                "portfolio_equity": snapshot.equity,
                "reserved_exposure": snapshot.reserved_exposure,
            }
        )
        return self.repository.persist_decision(
            principal,
            snapshot,
            decision,
            as_of=as_of,
            input_hash=input_hash,
            pricing_rejections=dict(rejection_counts),
            top_n=top_n,
            watchlist=watchlist,
            analysis_summary=analysis_summary,
        )

    def list(
        self,
        principal: Principal,
        portfolio_id: str,
        *,
        slate_date: date | None,
        upcoming_as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.list_recommendations(
            principal,
            portfolio_id,
            slate_date=slate_date,
            upcoming_as_of=upcoming_as_of,
        )

    def latest_decision(self, principal: Principal, portfolio_id: str, *, slate_date: date | None) -> dict[str, Any] | None:
        return self.repository.latest_decision_summary(principal, portfolio_id, slate_date=slate_date)

    def watchlist(self, principal: Principal, portfolio_id: str, *, as_of: datetime) -> dict[str, Any]:
        return self.repository.list_watchlist(principal, portfolio_id, as_of=as_of)

    def approve(self, principal: Principal, recommendation_id: str, *, idempotency_key: str | None) -> dict[str, Any]:
        return self.repository.approve(principal, recommendation_id, idempotency_key=idempotency_key)

    def reject(self, principal: Principal, recommendation_id: str) -> dict[str, Any]:
        return self.repository.reject(principal, recommendation_id)

    def risk(self, principal: Principal, portfolio_id: str, slate_date: date) -> dict[str, Any]:
        return self.repository.risk_summary(principal, portfolio_id, slate_date)

    def _registration(self, market_type: str) -> Any:
        model_id = RETAINED_MODELS[market_type]
        registration = self.registry_repository.get_model(model_id, "1.0.0")
        if registration is None:
            raise RegistryError(
                f"retained registry entry {model_id}@1.0.0 is unavailable; run the registry sync command"
            )
        return registration


def build_recommendation_policies(values: Mapping[str, Any]) -> tuple[QualificationPolicy, RiskPolicy, ParlayPolicy]:
    return (
        QualificationPolicy(
            minimum_ev=values["minimum_ev"],
            minimum_edge=values["minimum_edge"],
            maximum_dispersion=values["maximum_dispersion"],
            minimum_books=values["minimum_books"],
            maximum_market_age_seconds=values["maximum_market_age_seconds"],
            core_minimum_ev=values["core_minimum_ev"],
            core_minimum_edge=values["core_minimum_edge"],
        ),
        RiskPolicy(
            kelly_fraction=values["kelly_fraction"],
            minimum_stake=values["minimum_stake"],
            maximum_stake=values["maximum_stake"],
            maximum_core_bet_fraction=values["maximum_core_bet_fraction"],
            maximum_opportunistic_bet_fraction=values["maximum_opportunistic_bet_fraction"],
            maximum_daily_fraction=values["maximum_daily_fraction"],
            maximum_game_fraction=values["maximum_game_fraction"],
            maximum_team_fraction=values["maximum_team_fraction"],
            maximum_market_fraction=values["maximum_market_fraction"],
            maximum_correlated_fraction=values["maximum_correlated_fraction"],
            unit_fraction=values["unit_fraction"],
            reduced_risk_drawdown=values["reduced_risk_drawdown"],
            paused_drawdown=values["paused_drawdown"],
            bankroll_floor_fraction_of_start=values["bankroll_floor_fraction_of_start"],
        ),
        ParlayPolicy(
            enabled=values["parlay_enabled"],
            minimum_joint_ev=values["parlay_minimum_ev"],
            kelly_fraction=values["parlay_kelly_fraction"],
            maximum_parlay_fraction=values["parlay_maximum_fraction"],
            maximum_daily_parlay_fraction=values["parlay_daily_fraction"],
        ),
    )


ODDS_BANDS: tuple[tuple[str, int | None, int | None], ...] = (
    ("lte_-221", None, -221),
    ("-220_to_-151", -220, -151),
    ("-150_to_-121", -150, -121),
    ("-120_to_+120", -120, 120),
    ("+121_to_+150", 121, 150),
    ("+151_to_+220", 151, 220),
    ("+221_to_+300", 221, 300),
    ("+301_to_+500", 301, 500),
    ("gt_+500", 501, None),
)


def build_candidate_diagnostics(
    candidates: Sequence[CandidateEvaluation],
    watchlist: Sequence[Mapping[str, Any]],
    recommendations: Sequence[StraightRecommendation],
) -> dict[str, Any]:
    """Summarize candidate survival without changing qualification or ranking."""
    watchlist_ids = {str(item["watchlist_id"]) for item in watchlist}
    actionable_ids = {item.candidate.candidate_id for item in recommendations}
    by_market = {market: _empty_stage_counts() for market in ("moneyline", "spread", "total")}
    by_odds_band = {label: _empty_stage_counts() for label, _, _ in ODDS_BANDS}
    practical_core = _empty_stage_counts()
    for candidate in candidates:
        market_counts = by_market.setdefault(
            candidate.opportunity.market_type,
            _empty_stage_counts(),
        )
        band_counts = by_odds_band[_odds_band(candidate.opportunity.best_american_odds)]
        for counts in (market_counts, band_counts):
            _increment_candidate_stage(counts, candidate, watchlist_ids, actionable_ids)
        if -220 <= candidate.opportunity.best_american_odds <= 220:
            _increment_candidate_stage(practical_core, candidate, watchlist_ids, actionable_ids)
    return {
        "by_market": by_market,
        "by_odds_band": by_odds_band,
        "practical_core_odds_band": {
            "minimum_american_odds": -220,
            "maximum_american_odds": 220,
            **practical_core,
        },
    }


def _empty_stage_counts() -> dict[str, int]:
    return {
        "calculable": 0,
        "positive_edge": 0,
        "positive_ev": 0,
        "pricing_qualified": 0,
        "watchlist": 0,
        "portfolio_qualified": 0,
        "actionable": 0,
    }


def _increment_candidate_stage(
    counts: dict[str, int],
    candidate: CandidateEvaluation,
    watchlist_ids: set[str],
    actionable_ids: set[str],
) -> None:
    counts["calculable"] += 1
    counts["positive_edge"] += int(candidate.edge > 0)
    counts["positive_ev"] += int(candidate.ev_per_unit > 0)
    counts["pricing_qualified"] += int(not candidate.opportunity.pricing_gate_failures)
    counts["watchlist"] += int(candidate.candidate_id in watchlist_ids)
    counts["portfolio_qualified"] += int(candidate.qualified)
    counts["actionable"] += int(candidate.candidate_id in actionable_ids)


def _odds_band(odds: int) -> str:
    for label, lower, upper in ODDS_BANDS:
        if (lower is None or odds >= lower) and (upper is None or odds <= upper):
            return label
    raise AssertionError("American odds did not map to a diagnostic band")


def _serialize_qualified_non_actionable(
    item: QualifiedNonActionableOpportunity,
    *,
    as_of: datetime,
    timing: Mapping[str, Any] | None,
    qualification_policy_version: str,
    risk_policy_version: str,
) -> dict[str, Any]:
    candidate = item.candidate
    opportunity = candidate.opportunity
    observed_times = tuple(
        value.selection_observed_at
        for value in opportunity.book_probabilities
        if value.selection_observed_at is not None
    )
    latest_observed = max(observed_times, default=as_of)
    freshness_age_seconds = max(0, int((as_of - latest_observed).total_seconds()))
    timing_payload = timing or {}
    return {
        "qualified_opportunity_id": candidate.candidate_id,
        "event_id": str(opportunity.event_id),
        "slate_date": opportunity.scheduled_start_utc.date().isoformat(),
        "scheduled_start": opportunity.scheduled_start_utc.isoformat(),
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
        "push_probability": _number(candidate.push_probability),
        "edge": _number(candidate.edge),
        "ev_per_unit": _number(candidate.ev_per_unit),
        "books_count": opportunity.books_contributing,
        "dispersion": _number(opportunity.consensus_dispersion),
        "freshness_age_seconds": freshness_age_seconds,
        "calculated_stake": _number(item.calculated_stake),
        "minimum_operational_stake": _number(item.minimum_operational_stake),
        "raw_kelly_fraction": _number(item.raw_kelly_fraction),
        "adjusted_kelly_fraction": _number(item.adjusted_kelly_fraction),
        "ranking_score": _number(candidate.ranking_score),
        "classification": candidate.classification.value if candidate.classification else None,
        "blocker": item.blocker,
        "risk_adjustments": list(item.risk_adjustments),
        "source_observation_ids": [str(value) for value in opportunity.source_observation_ids],
        "snapshot_ids": [str(value) for value in opportunity.snapshot_ids],
        "best_executable_observation_id": str(opportunity.best_executable_observation_id),
        "model_id": candidate.fair_value.model_id,
        "model_version": candidate.fair_value.model_version,
        "model_status": candidate.fair_value.model_status.value,
        "pricing_policy_version": opportunity.pricing_policy_version,
        "qualification_policy_version": qualification_policy_version,
        "risk_policy_version": risk_policy_version,
        "market_probability_policy_version": opportunity.market_probability_policy_version,
        "timing_classification": timing_payload.get("timing_classification"),
        "primary_horizon_at": (
            timing_payload["primary_horizon_at"].isoformat()
            if isinstance(timing_payload.get("primary_horizon_at"), datetime)
            else timing_payload.get("primary_horizon_at")
        ),
        "qualified": True,
        "actionable": False,
        "approvable": False,
        "opportunity_hash": item.opportunity_hash,
    }


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
