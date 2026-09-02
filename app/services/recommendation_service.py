from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from app.domain.identity import Principal
from app.domain.model_registry import ConsensusFairValueInput, RegistryError, canonical_hash
from app.domain.portfolio_engine import (
    ParlayOffer,
    ParlayPolicy,
    QualificationPolicy,
    RiskPolicy,
    construct_portfolio,
    evaluate_candidate,
)
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
        for opportunity in pricing.opportunities:
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
                        push_probability=None if opportunity.market_type == "moneyline" else Decimal(0),
                        as_of=pricing.as_of,
                        source_books=tuple(item.sportsbook_key for item in opportunity.book_probabilities),
                        consensus_dispersion=opportunity.consensus_dispersion,
                        quality_metadata={
                            "uncertainty": opportunity.uncertainty_indicator,
                            "quality_warnings": list(opportunity.quality_warnings),
                            "fresh": True,
                        },
                        provenance={
                            "pricing_policy_version": opportunity.pricing_policy_version,
                            "qualification_policy_version": opportunity.qualification_policy_version,
                            "source_observation_ids": [str(value) for value in opportunity.source_observation_ids],
                            "snapshot_ids": [str(value) for value in opportunity.snapshot_ids],
                            "best_executable_observation_id": str(opportunity.best_executable_observation_id),
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
                rejection_counts.update(evaluation.rejection_reasons)
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
        input_hash = canonical_hash(
            {
                "portfolio_id": portfolio_id,
                "slate_date": slate_date,
                "as_of": as_of,
                "pricing_policy": pricing.pricing_policy_version,
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
