from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import CanonicalEvent
from app.db.models import Bet, BetApproval, BetStateTransition, LedgerEntry, Owner, Portfolio, Recommendation
from app.db.portfolio_models import RecommendationDecisionRun, RecommendationLeg
from app.domain.errors import (
    InsufficientBankrollError,
    PortfolioAccessDeniedError,
    RecommendationNotFoundError,
    RecommendationStateError,
)
from app.domain.identity import Principal
from app.domain.money import money, money_json
from app.domain.portfolio_engine import (
    PARLAY_POLICY_VERSION,
    RECOMMENDATION_VERSION,
    RISK_POLICY_VERSION,
    OpenExposure,
    ParlayPolicy,
    ParlayRecommendation,
    PortfolioDecision,
    PortfolioSnapshot,
    RiskPolicy,
    StraightRecommendation,
    portfolio_state,
)
from app.domain.model_registry import canonical_hash
from app.domain.recommendation_timing import classify_recommendation_timing
from app.time import utc_now


class SqlAlchemyRecommendationRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        starting_capital: Decimal,
        *,
        risk_policy: RiskPolicy | None = None,
        parlay_policy: ParlayPolicy | None = None,
        clock: Any = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.starting_capital = money(starting_capital)
        self.risk_policy = risk_policy or RiskPolicy()
        self.parlay_policy = parlay_policy or ParlayPolicy()
        self.clock = clock

    def portfolio_snapshot(self, principal: Principal, portfolio_external_id: str, slate_date: date) -> PortfolioSnapshot:
        with self.session_factory.begin() as session:
            owner = self._owner(session, principal)
            portfolio = self._portfolio(session, owner.id, portfolio_external_id)
            cash = self._cash(session, portfolio.id)
            open_bets = list(session.scalars(select(Bet).where(Bet.portfolio_id == portfolio.id, Bet.status == "open")))
            reserved = sum((money(item.stake) for item in open_bets), Decimal(0))
            settled = list(
                session.scalars(
                    select(Bet)
                    .where(Bet.portfolio_id == portfolio.id, Bet.status == "settled")
                    .order_by(Bet.settled_at, Bet.id)
                )
            )
            realized = sum((money(item.realized_pnl or 0) for item in settled), Decimal(0))
            running = money(portfolio.starting_capital)
            peak = running
            for item in settled:
                running += money(item.realized_pnl or 0)
                peak = max(peak, running)
            exposures: list[OpenExposure] = []
            for bet in open_bets:
                exposures.extend(self._open_exposures(session, bet))
            return PortfolioSnapshot(
                portfolio_id=portfolio.external_id,
                slate_date=slate_date,
                starting_bankroll=money(portfolio.starting_capital),
                cash=cash,
                reserved_exposure=money(reserved),
                equity=money(cash + reserved),
                peak_equity=money(peak),
                realized_pnl=money(realized),
                open_exposures=tuple(exposures),
            )

    def persist_decision(
        self,
        principal: Principal,
        snapshot: PortfolioSnapshot,
        decision: PortfolioDecision,
        *,
        as_of: datetime,
        input_hash: str,
        pricing_rejections: Mapping[str, int],
        top_n: int,
        watchlist: list[dict[str, Any]] | None = None,
        analysis_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        watchlist = watchlist or []
        analysis_summary = dict(analysis_summary or {})
        with self.session_factory.begin() as session:
            owner = self._owner(session, principal)
            portfolio = self._portfolio(session, owner.id, snapshot.portfolio_id)
            output_hash = canonical_hash(
                {
                    "portfolio_id": str(portfolio.id),
                    "slate_date": snapshot.slate_date,
                    "decision_hash": decision.decision_hash,
                    "input_hash": input_hash,
                    "watchlist": watchlist,
                    "analysis_summary": analysis_summary,
                }
            )
            existing = session.scalar(
                select(RecommendationDecisionRun).where(RecommendationDecisionRun.output_hash == output_hash)
            )
            if existing is not None:
                return self._serialize_run(session, existing)
            run_id = uuid4()
            run = RecommendationDecisionRun(
                id=run_id,
                external_id=str(run_id),
                portfolio_id=portfolio.id,
                league="NCAAF",
                slate_date=snapshot.slate_date,
                as_of=as_of,
                status="completed",
                portfolio_state=decision.portfolio_state.value,
                top_n=top_n,
                starting_bankroll=snapshot.starting_bankroll,
                cash=snapshot.cash,
                reserved_exposure=snapshot.reserved_exposure,
                equity=snapshot.equity,
                peak_equity=snapshot.peak_equity,
                drawdown_fraction=snapshot.drawdown_fraction,
                qualification_policy_version=decision.qualification_policy_version,
                risk_policy_version=decision.risk_policy_version,
                parlay_policy_version=decision.parlay_policy_version,
                pass_reasons=list(decision.pass_reasons),
                rejection_summary=dict(pricing_rejections),
                analysis_summary=analysis_summary,
                watchlist_items=watchlist,
                input_hash=input_hash,
                output_hash=output_hash,
                created_at=self.clock(),
            )
            session.add(run)
            session.flush()
            for portfolio_rank, item in enumerate(decision.straight_recommendations, start=1):
                session.add(
                    self._straight_row(
                        portfolio.id,
                        run.id,
                        run.output_hash,
                        item,
                        portfolio_rank=portfolio_rank,
                    )
                )
            if decision.parlay is not None:
                row = self._parlay_row(portfolio.id, run.id, run.output_hash, decision.parlay)
                session.add(row)
                session.flush()
                for index, leg in enumerate(decision.parlay.legs):
                    session.add(self._leg_row(row.id, index, leg))
            session.flush()
            return self._serialize_run(session, run)

    def list_recommendations(
        self,
        principal: Principal,
        portfolio_external_id: str,
        *,
        slate_date: date | None = None,
        upcoming_as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            owner = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
            if owner is None:
                return []
            portfolio = session.scalar(select(Portfolio).where(Portfolio.external_id == portfolio_external_id))
            if portfolio is None:
                return []
            if portfolio.owner_id != owner.id:
                raise PortfolioAccessDeniedError
            statement = select(Recommendation).where(Recommendation.portfolio_id == portfolio.id)
            if slate_date is not None:
                statement = statement.join(
                    RecommendationDecisionRun,
                    Recommendation.decision_run_id == RecommendationDecisionRun.id,
                ).where(RecommendationDecisionRun.slate_date == slate_date)
            if upcoming_as_of is not None:
                latest_by_slate = (
                    select(
                        RecommendationDecisionRun.slate_date.label("slate_date"),
                        func.max(RecommendationDecisionRun.as_of).label("latest_as_of"),
                    )
                    .where(
                        RecommendationDecisionRun.portfolio_id == portfolio.id,
                        RecommendationDecisionRun.slate_date >= upcoming_as_of.date(),
                    )
                    .group_by(RecommendationDecisionRun.slate_date)
                    .subquery()
                )
                statement = (
                    statement.join(
                        RecommendationDecisionRun,
                        Recommendation.decision_run_id == RecommendationDecisionRun.id,
                    )
                    .join(
                        latest_by_slate,
                        and_(
                            latest_by_slate.c.slate_date == RecommendationDecisionRun.slate_date,
                            latest_by_slate.c.latest_as_of == RecommendationDecisionRun.as_of,
                        ),
                    )
                    .where(
                        or_(
                            Recommendation.scheduled_start > upcoming_as_of,
                            Recommendation.recommendation_kind == "parlay",
                        )
                    )
                )
            rows = list(
                session.scalars(
                    statement.order_by(
                        Recommendation.created_at.desc(),
                        Recommendation.external_id,
                    )
                )
            )
            serialized = [self._serialize_recommendation(session, row) for row in rows]
            if slate_date is not None or upcoming_as_of is not None:
                serialized.sort(key=_serialized_recommendation_order)
            return serialized

    def latest_decision_summary(
        self,
        principal: Principal,
        portfolio_external_id: str,
        *,
        slate_date: date | None = None,
    ) -> dict[str, Any] | None:
        with self.session_factory() as session:
            owner = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
            if owner is None:
                return None
            portfolio = session.scalar(select(Portfolio).where(Portfolio.external_id == portfolio_external_id))
            if portfolio is None:
                return None
            if portfolio.owner_id != owner.id:
                raise PortfolioAccessDeniedError
            statement = select(RecommendationDecisionRun).where(
                RecommendationDecisionRun.portfolio_id == portfolio.id
            )
            if slate_date is not None:
                statement = statement.where(RecommendationDecisionRun.slate_date == slate_date)
            run = session.scalar(
                statement.order_by(RecommendationDecisionRun.as_of.desc(), RecommendationDecisionRun.id).limit(1)
            )
            if run is None:
                return None
            return {
                "decision_run_id": run.external_id,
                "as_of": _iso(run.as_of),
                "portfolio_state": run.portfolio_state,
                "pass_reasons": list(run.pass_reasons),
                "rejection_summary": dict(run.rejection_summary),
                "analysis_summary": dict(run.analysis_summary),
                "watchlist_count": len(run.watchlist_items),
                "policy_versions": {
                    "qualification": run.qualification_policy_version,
                    "risk": run.risk_policy_version,
                    "parlay": run.parlay_policy_version,
                },
                "decision_hash": run.output_hash,
            }

    def list_watchlist(
        self,
        principal: Principal,
        portfolio_external_id: str,
        *,
        as_of: datetime,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            owner = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
            if owner is None:
                return _empty_watchlist(as_of)
            portfolio = session.scalar(select(Portfolio).where(Portfolio.external_id == portfolio_external_id))
            if portfolio is None:
                return _empty_watchlist(as_of)
            if portfolio.owner_id != owner.id:
                raise PortfolioAccessDeniedError
            latest_by_slate = (
                select(
                    RecommendationDecisionRun.slate_date.label("slate_date"),
                    func.max(RecommendationDecisionRun.as_of).label("latest_as_of"),
                )
                .where(
                    RecommendationDecisionRun.portfolio_id == portfolio.id,
                    RecommendationDecisionRun.slate_date >= as_of.date(),
                )
                .group_by(RecommendationDecisionRun.slate_date)
                .subquery()
            )
            matched_runs = list(
                session.scalars(
                    select(RecommendationDecisionRun)
                    .join(
                        latest_by_slate,
                        and_(
                            latest_by_slate.c.slate_date == RecommendationDecisionRun.slate_date,
                            latest_by_slate.c.latest_as_of == RecommendationDecisionRun.as_of,
                        ),
                    )
                    .where(RecommendationDecisionRun.portfolio_id == portfolio.id)
                    .order_by(RecommendationDecisionRun.slate_date, RecommendationDecisionRun.id)
                )
            )
            runs_by_slate: dict[date, RecommendationDecisionRun] = {}
            for run in matched_runs:
                runs_by_slate.setdefault(run.slate_date, run)
            runs = list(runs_by_slate.values())
            items = [
                dict(item)
                for run in runs
                for item in run.watchlist_items
                if datetime.fromisoformat(str(item["scheduled_start"])) > _aware(as_of)
            ]
            items.sort(
                key=lambda item: (
                    int(item["failed_gate_count"]),
                    Decimal(str(item["distance_to_qualification"])),
                    -Decimal(str(item["ev_per_unit"])),
                    -Decimal(str(item["edge"])),
                    str(item["scheduled_start"]),
                    str(item["watchlist_id"]),
                )
            )
            qualified_opportunities = [
                dict(item)
                for run in runs
                for item in run.analysis_summary.get("qualified_opportunities", [])
                if isinstance(item, Mapping)
                and datetime.fromisoformat(str(item["scheduled_start"])) > _aware(as_of)
            ]
            qualified_opportunities.sort(
                key=lambda item: (
                    -Decimal(str(item.get("ranking_score", 0))),
                    str(item["scheduled_start"]),
                    str(item["qualified_opportunity_id"]),
                )
            )
            actionable = 0
            run_ids = [run.id for run in runs]
            if run_ids:
                actionable = int(
                    session.scalar(
                        select(func.count())
                        .select_from(Recommendation)
                        .where(
                            Recommendation.decision_run_id.in_(run_ids),
                            Recommendation.recommendation_kind == "straight",
                        )
                    )
                    or 0
                )
            slates = []
            aggregate_funnel: Counter[str] = Counter()
            aggregate_rejections: Counter[str] = Counter()
            funnel_samples: list[dict[str, int]] = []
            qualified_total = 0
            for run in runs:
                summary = dict(run.analysis_summary)
                funnel = {
                    key: int(value)
                    for key, value in dict(summary.get("pricing_funnel", {})).items()
                    if isinstance(value, int)
                }
                aggregate_funnel.update(funnel)
                funnel_samples.append(funnel)
                rejections = {
                    key: int(value)
                    for key, value in dict(run.rejection_summary).items()
                    if isinstance(value, int)
                }
                aggregate_rejections.update(rejections)
                slate_items = [item for item in items if item.get("slate_date") == run.slate_date.isoformat()]
                slate_actionable = int(
                    session.scalar(
                        select(func.count())
                        .select_from(Recommendation)
                        .where(
                            Recommendation.decision_run_id == run.id,
                            Recommendation.recommendation_kind == "straight",
                        )
                    )
                    or 0
                )
                slate_qualified = int(
                    summary.get(
                        "qualified_candidates",
                        funnel.get("qualified_candidates", slate_actionable),
                    )
                )
                qualified_total += slate_qualified
                slates.append(
                    {
                        "slate_date": run.slate_date.isoformat(),
                        "weekday": run.slate_date.strftime("%A"),
                        "as_of": _iso(run.as_of),
                        "games_analyzed": int(summary.get("games_analyzed", 0)),
                        "qualified_recommendations": slate_qualified,
                        "actionable_recommendations": slate_actionable,
                        "qualified_non_actionable_count": len(
                            summary.get("qualified_opportunities", [])
                        ),
                        "watchlist_count": len(slate_items),
                        "pricing_funnel": funnel,
                        "rejection_counts": dict(sorted(rejections.items())),
                        "pricing_pipeline_status": str(
                            summary.get("pricing_pipeline_status", "HEALTHY")
                        ),
                        "pricing_pipeline_status_reason": summary.get(
                            "pricing_pipeline_status_reason"
                        ),
                    }
                )
            degraded = [item for item in slates if item["pricing_pipeline_status"] == "DEGRADED"]
            _normalize_aggregate_funnel_gauges(aggregate_funnel, funnel_samples)
            return {
                "as_of": _iso(as_of),
                "upcoming_games_analyzed": sum(
                    int(run.analysis_summary.get("games_analyzed", 0)) for run in runs
                ),
                "qualified_recommendations": qualified_total,
                "actionable_recommendations": actionable,
                "watchlist_count": len(items),
                "watchlist_version": "ncaaf-watchlist-v2",
                "pricing_funnel": dict(sorted(aggregate_funnel.items())),
                "rejection_counts": dict(sorted(aggregate_rejections.items())),
                "pricing_pipeline_status": "DEGRADED" if degraded else "HEALTHY",
                "pricing_pipeline_status_reason": (
                    degraded[0]["pricing_pipeline_status_reason"] if degraded else None
                ),
                "slates": slates,
                "items": items,
                "qualified_opportunities": qualified_opportunities,
            }

    def reject(self, principal: Principal, recommendation_id: str) -> dict[str, Any]:
        with self.session_factory.begin() as session:
            recommendation = self._owned_recommendation(session, principal, recommendation_id, lock=True)
            if recommendation.status != "proposed":
                raise RecommendationStateError("Only proposed recommendations can be rejected")
            recommendation.status = "rejected"
            recommendation.rejected_at = self.clock()
            session.flush()
            return self._serialize_recommendation(session, recommendation)

    def approve(
        self,
        principal: Principal,
        recommendation_id: str,
        *,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        del idempotency_key  # recommendation state is the durable idempotency boundary
        with self.session_factory.begin() as session:
            owner = self._owner(session, principal)
            session.scalar(select(Owner.id).where(Owner.id == owner.id).with_for_update())
            recommendation = self._owned_recommendation(session, principal, recommendation_id, lock=True)
            if recommendation.status == "approved":
                approval = session.scalar(
                    select(BetApproval).where(BetApproval.recommendation_id == recommendation.id)
                )
                if approval is None:
                    raise RecommendationStateError("Approved recommendation is missing its bet approval")
                bet = session.get(Bet, approval.bet_id)
                if bet is None:
                    raise RecommendationStateError("Approved recommendation references a missing bet")
                return {"message": "Recommendation already approved", "bet_id": bet.external_id, "bankroll_after": money_json(self._cash(session, recommendation.portfolio_id))}
            if recommendation.status != "proposed":
                raise RecommendationStateError("Only proposed recommendations can be approved")
            stake = money(recommendation.recommended_stake or 0)
            if stake <= 0:
                raise RecommendationStateError("Recommendation has no positive approved stake")
            cash = self._cash(session, recommendation.portfolio_id)
            if cash < stake:
                raise InsufficientBankrollError
            run = session.get(RecommendationDecisionRun, recommendation.decision_run_id)
            if run is None:
                raise RecommendationStateError("Recommendation is missing its decision run")
            self._validate_approval_risk(session, recommendation, run, stake, cash)
            now = self.clock()
            bet_id = uuid4()
            bet = Bet(
                id=bet_id,
                external_id=str(bet_id),
                portfolio_id=recommendation.portfolio_id,
                bet_kind=recommendation.recommendation_kind,
                classification=recommendation.classification,
                recommendation_hash=recommendation.recommendation_hash,
                decision_metadata={
                    "decision_run": run.external_id if run else None,
                    "confidence": (recommendation.uncertainty_metadata or {}).get("uncertainty", "unknown"),
                    "risk_adjustments": recommendation.risk_adjustments or [],
                    "provenance": recommendation.provenance or {},
                },
                provider_event_id=recommendation.provider_event_id,
                canonical_event_id=recommendation.canonical_event_id,
                bet_date=run.slate_date if run else now.date(),
                sport="NCAAF",
                league="NCAAF",
                event_name=(
                    "Parlay of the Day"
                    if recommendation.recommendation_kind == "parlay"
                    else recommendation.selection
                ),
                home_team=recommendation.home_team,
                away_team=recommendation.away_team,
                scheduled_start=recommendation.scheduled_start,
                market_type=recommendation.market_type,
                period=recommendation.period,
                selection=recommendation.selection,
                selection_side=recommendation.selection_side,
                point=recommendation.point,
                sportsbook=recommendation.sportsbook,
                entry_american_odds=recommendation.offered_american_odds,
                stake=stake,
                model_probability=None,
                book_probability=recommendation.implied_probability,
                consensus_probability=recommendation.consensus_probability,
                fair_probability=recommendation.fair_probability,
                probability_edge=recommendation.probability_edge,
                ev_per_unit=recommendation.ev_per_unit,
                recommendation_version=recommendation.recommendation_version,
                model_version=recommendation.model_version,
                policy_version=recommendation.policy_version,
                approved_at=now,
                approval_source="recommendation_api",
                placed_at=now,
                created_at=now,
                status="open",
            )
            session.add(bet)
            session.flush()
            session.add_all(
                [
                    BetApproval(
                        id=uuid4(),
                        bet_id=bet.id,
                        owner_id=owner.id,
                        recommendation_id=recommendation.id,
                        source="recommendation_api",
                        metadata_json={"explicit_human_approval": True, "recommended_stake": str(stake)},
                        approved_at=now,
                    ),
                    BetStateTransition(
                        id=uuid4(), bet_id=bet.id, from_status=None, to_status="open",
                        source="recommendation_api", transitioned_at=now,
                    ),
                    LedgerEntry(
                        id=uuid4(), portfolio_id=recommendation.portfolio_id, entry_type="bet_stake",
                        amount=-stake, related_bet_id=bet.id, reference=f"bet:{bet.external_id}:stake",
                        metadata_json={"purpose": "reserve approved recommendation stake", "recommendation_id": recommendation.external_id},
                        created_at=now,
                    ),
                ]
            )
            recommendation.status = "approved"
            recommendation.approved_at = now
            session.flush()
            return {"message": "Recommendation approved and paper bet recorded", "bet_id": bet.external_id, "bankroll_after": money_json(self._cash(session, recommendation.portfolio_id))}

    def risk_summary(self, principal: Principal, portfolio_external_id: str, slate_date: date) -> dict[str, Any]:
        snapshot = self.portfolio_snapshot(principal, portfolio_external_id, slate_date)
        state = portfolio_state(snapshot, self.risk_policy)
        floor = snapshot.starting_bankroll * self.risk_policy.bankroll_floor_fraction_of_start
        if snapshot.equity <= floor:
            state_reason = "bankroll_floor"
        elif snapshot.drawdown_fraction >= self.risk_policy.paused_drawdown:
            state_reason = "paused_drawdown_threshold"
        elif snapshot.drawdown_fraction >= self.risk_policy.reduced_risk_drawdown:
            state_reason = "reduced_risk_drawdown_threshold"
        else:
            state_reason = "within_policy"
        by_game: defaultdict[str, Decimal] = defaultdict(Decimal)
        by_team: defaultdict[str, Decimal] = defaultdict(Decimal)
        by_market: defaultdict[str, Decimal] = defaultdict(Decimal)
        by_kind: defaultdict[str, Decimal] = defaultdict(Decimal)
        for item in snapshot.open_exposures:
            by_game[item.event_id] += item.stake
            by_market[item.market_type] += item.stake
            by_kind[item.bet_kind] += item.stake
            for team in item.teams:
                by_team[team] += item.stake
        return {
            "portfolio_id": snapshot.portfolio_id,
            "slate_date": slate_date.isoformat(),
            "portfolio_state": state.value,
            "state_reason": state_reason,
            "cash": money_json(snapshot.cash),
            "reserved_exposure": money_json(snapshot.reserved_exposure),
            "equity": money_json(snapshot.equity),
            "peak_equity": money_json(snapshot.peak_equity),
            "drawdown_fraction": float(snapshot.drawdown_fraction),
            "by_game": {key: money_json(value) for key, value in sorted(by_game.items())},
            "by_team": {key: money_json(value) for key, value in sorted(by_team.items())},
            "by_market": {key: money_json(value) for key, value in sorted(by_market.items())},
            "by_kind": {key: money_json(value) for key, value in sorted(by_kind.items())},
        }

    def _owner(self, session: Session, principal: Principal) -> Owner:
        owner = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
        if owner is None:
            owner = Owner(id=uuid4(), external_id=principal.external_id, display_name=principal.display_name, status="active", created_at=self.clock())
            session.add(owner)
            session.flush()
        return owner

    def _portfolio(self, session: Session, owner_id: UUID, external_id: str) -> Portfolio:
        portfolio = session.scalar(select(Portfolio).where(Portfolio.external_id == external_id))
        if portfolio is not None:
            if portfolio.owner_id != owner_id:
                raise PortfolioAccessDeniedError
            return portfolio
        portfolio = Portfolio(id=uuid4(), external_id=external_id, owner_id=owner_id, starting_capital=self.starting_capital, currency="USD", status="active", created_at=self.clock())
        session.add(portfolio)
        session.flush()
        session.add(LedgerEntry(id=uuid4(), portfolio_id=portfolio.id, entry_type="initial_funding", amount=self.starting_capital, reference="initial_funding", metadata_json={"source": "portfolio_creation"}, created_at=self.clock()))
        session.flush()
        return portfolio

    def _owned_recommendation(self, session: Session, principal: Principal, external_id: str, *, lock: bool) -> Recommendation:
        statement = select(Recommendation).where(Recommendation.external_id == external_id)
        if lock:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise RecommendationNotFoundError
        portfolio = session.get(Portfolio, row.portfolio_id)
        owner = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
        if owner is None or portfolio is None or portfolio.owner_id != owner.id:
            raise PortfolioAccessDeniedError
        return row

    def _straight_row(
        self,
        portfolio_id: UUID,
        run_id: UUID,
        run_hash: str,
        item: StraightRecommendation,
        *,
        portfolio_rank: int,
    ) -> Recommendation:
        candidate = item.candidate
        opportunity = candidate.opportunity
        persistent_hash = canonical_hash({"run_hash": run_hash, "recommendation_hash": item.recommendation_hash})
        return Recommendation(
            id=uuid4(), external_id=f"rec-{persistent_hash[:32]}", portfolio_id=portfolio_id,
            decision_run_id=run_id, canonical_event_id=opportunity.event_id, recommendation_kind="straight",
            league="NCAAF", market_type=opportunity.market_type, period=opportunity.period,
            selection=opportunity.selection_name, selection_side=opportunity.selection_side, point=opportunity.point,
            home_team=opportunity.home_team, away_team=opportunity.away_team,
            scheduled_start=opportunity.scheduled_start_utc,
            sportsbook=opportunity.best_sportsbook_key, offered_american_odds=opportunity.best_american_odds,
            best_executable_observation_id=opportunity.best_executable_observation_id,
            implied_probability=candidate.implied_probability, push_probability=candidate.push_probability,
            consensus_probability=candidate.win_probability, fair_probability=candidate.win_probability,
            probability_edge=candidate.edge, ev_per_unit=candidate.ev_per_unit,
            uncertainty_metadata={
                **dict(candidate.fair_value.uncertainty_quality),
                "quote_integrity": candidate.quote_integrity,
            },
            executable_alternatives=_alternatives(opportunity), risk_adjustments=list(item.risk_adjustments),
            provenance={
                **dict(candidate.fair_value.provenance),
                "fair_value_hash": candidate.fair_value.fair_value_hash,
                "source_observation_ids": [str(value) for value in opportunity.source_observation_ids],
                "portfolio_rank": portfolio_rank,
                "ranking_score": str(candidate.ranking_score),
                "expected_log_growth": str(candidate.expected_log_growth),
                "robust_expected_log_growth": str(candidate.robust_expected_log_growth),
                "ranking_kelly_fraction": str(candidate.ranking_kelly_fraction),
                "quote_integrity": candidate.quote_integrity,
                "books_contributing": opportunity.books_contributing,
                "consensus_dispersion": str(opportunity.consensus_dispersion),
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
                "market_probability_policy_version": (
                    opportunity.market_probability_policy_version
                ),
                "market_curve_artifact_hash": opportunity.market_curve_artifact_hash,
                "outlier_sportsbooks": list(opportunity.outlier_sportsbooks),
                "best_executable_is_consensus_outlier": (
                    opportunity.best_sportsbook_key in opportunity.outlier_sportsbooks
                ),
                "research_explanation": _straight_explanation(item),
            },
            classification=item.candidate.classification.value if item.candidate.classification else None,
            recommended_stake=item.recommended_stake, bankroll_fraction=item.bankroll_fraction, units=item.units,
            raw_kelly_fraction=item.raw_kelly_fraction, adjusted_kelly_fraction=item.adjusted_kelly_fraction,
            recommendation_hash=persistent_hash, recommendation_version=RECOMMENDATION_VERSION,
            model_version=f"{candidate.fair_value.model_id}@{candidate.fair_value.model_version}",
            policy_version=RISK_POLICY_VERSION, status="proposed", created_at=self.clock(),
        )

    def _parlay_row(self, portfolio_id: UUID, run_id: UUID, run_hash: str, item: ParlayRecommendation) -> Recommendation:
        selection = " + ".join(leg.candidate.opportunity.selection_name for leg in item.legs)
        persistent_hash = canonical_hash({"run_hash": run_hash, "recommendation_hash": item.recommendation_hash})
        return Recommendation(
            id=uuid4(), external_id=f"rec-{persistent_hash[:32]}", portfolio_id=portfolio_id,
            decision_run_id=run_id, recommendation_kind="parlay", league="NCAAF", market_type="parlay",
            period="multiple", selection=selection, sportsbook=item.offer.sportsbook_key,
            offered_american_odds=item.offer.american_odds, implied_probability=item.implied_probability,
            push_probability=Decimal(0), consensus_probability=item.joint_fair_probability,
            fair_probability=item.joint_fair_probability,
            probability_edge=item.joint_fair_probability - item.implied_probability, ev_per_unit=item.joint_ev_per_unit,
            uncertainty_metadata={
                "correlation_method": item.correlation_method,
                "correlation_adjustment": str(item.correlation_adjustment),
                "gross_payout_if_win": str(money(item.stake / item.implied_probability)),
                "expected_net_profit": str(money(item.expected_net_profit)),
                "incremental_exposure": {
                    key: str(value) for key, value in item.incremental_exposure.items()
                },
                "selection_score": str(item.selection_score),
            },
            risk_adjustments=["separate_parlay_sleeve", "duplicate_exposure_accounted"],
            provenance={
                **dict(item.offer.provenance),
                "selection_reason": "highest_eligible_expected_log_growth_score",
                "research_explanation": (
                    "Verified cross-event, disjoint-team quote with independently qualified legs; "
                    "selected by versioned expected log growth after duplicate-exposure penalty."
                ),
            },
            classification="OPPORTUNISTIC", recommended_stake=item.stake,
            bankroll_fraction=item.bankroll_fraction, units=item.units, recommendation_hash=persistent_hash,
            recommendation_version=RECOMMENDATION_VERSION, model_version="joint-market-consensus-v1",
            policy_version=PARLAY_POLICY_VERSION, status="proposed", created_at=self.clock(),
        )

    def _leg_row(self, recommendation_id: UUID, index: int, leg: StraightRecommendation) -> RecommendationLeg:
        item = leg.candidate
        return RecommendationLeg(
            id=uuid4(), recommendation_id=recommendation_id, leg_index=index, candidate_id=item.candidate_id,
            canonical_event_id=item.opportunity.event_id, market_type=item.opportunity.market_type,
            selection_side=item.opportunity.selection_side, selection=item.opportunity.selection_name,
            point=item.opportunity.point, sportsbook=item.opportunity.best_sportsbook_key,
            american_odds=item.opportunity.best_american_odds, fair_probability=item.win_probability,
            implied_probability=item.implied_probability, probability_edge=item.edge, ev_per_unit=item.ev_per_unit,
            model_id=item.fair_value.model_id, model_version=item.fair_value.model_version,
            provenance=dict(item.fair_value.provenance), created_at=self.clock(),
        )

    def _serialize_run(self, session: Session, run: RecommendationDecisionRun) -> dict[str, Any]:
        rows = list(
            session.scalars(
                select(Recommendation)
                .where(Recommendation.decision_run_id == run.id)
                .order_by(Recommendation.recommendation_kind, Recommendation.external_id)
            )
        )
        straight = [
            self._serialize_recommendation(session, row)
            for row in rows
            if row.recommendation_kind == "straight"
        ]
        straight.sort(key=_serialized_recommendation_order)
        parlay = next((self._serialize_recommendation(session, row) for row in rows if row.recommendation_kind == "parlay"), None)
        return {"decision_run_id": run.external_id, "as_of": _iso(run.as_of), "slate_date": run.slate_date.isoformat(), "portfolio_state": run.portfolio_state, "top_n": run.top_n, "pass_reasons": list(run.pass_reasons), "policy_versions": {"qualification": run.qualification_policy_version, "risk": run.risk_policy_version, "parlay": run.parlay_policy_version}, "portfolio": {"cash": money_json(run.cash), "reserved_exposure": money_json(run.reserved_exposure), "equity": money_json(run.equity), "peak_equity": money_json(run.peak_equity), "drawdown_fraction": float(run.drawdown_fraction)}, "straight_recommendations": straight, "parlay_of_the_day": parlay or {"status": "PASS", "reasons": [reason for reason in run.pass_reasons if reason.startswith("parlay_pass:")]}, "analysis_summary": dict(run.analysis_summary), "watchlist_count": len(run.watchlist_items), "decision_hash": run.output_hash}

    def _serialize_recommendation(self, session: Session, row: Recommendation) -> dict[str, Any]:
        legs = list(session.scalars(select(RecommendationLeg).where(RecommendationLeg.recommendation_id == row.id).order_by(RecommendationLeg.leg_index)))
        timing: dict[str, Any] = {}
        if row.decision_run_id is not None:
            run = session.get(RecommendationDecisionRun, row.decision_run_id)
            if run is not None:
                start = datetime.combine(run.slate_date, time.min, UTC)
                first_kickoff = session.scalar(
                    select(func.min(CanonicalEvent.scheduled_start_utc)).where(
                        CanonicalEvent.league == "NCAAF",
                        CanonicalEvent.scheduled_start_utc >= start,
                        CanonicalEvent.scheduled_start_utc < start + timedelta(days=1),
                    )
                )
                if first_kickoff is not None:
                    timing = classify_recommendation_timing(run.as_of, first_kickoff)
        return {
            "recommendation_id": row.external_id,
            "kind": row.recommendation_kind,
            "status": row.status,
            "event_id": str(row.canonical_event_id) if row.canonical_event_id else None,
            "home_team": row.home_team,
            "away_team": row.away_team,
            "scheduled_start": _iso(row.scheduled_start) if row.scheduled_start else None,
            "market": row.market_type,
            "side": row.selection_side,
            "selection": row.selection,
            "sportsbook": row.sportsbook,
            "point": _decimal(row.point),
            "odds": row.offered_american_odds,
            "fair_probability": _decimal(row.fair_probability),
            "implied_probability": _decimal(row.implied_probability),
            "push_probability": _decimal(row.push_probability),
            "edge": _decimal(row.probability_edge),
            "ev_per_unit": _decimal(row.ev_per_unit),
            "confidence_quality": row.uncertainty_metadata or {},
            "stake": money_json(row.recommended_stake or Decimal(0)),
            "bankroll_fraction": _decimal(row.bankroll_fraction),
            "units": _decimal(row.units),
            "raw_kelly_fraction": _decimal(row.raw_kelly_fraction),
            "adjusted_kelly_fraction": _decimal(row.adjusted_kelly_fraction),
            "portfolio_rank": (row.provenance or {}).get("portfolio_rank"),
            "ranking_score": _provenance_decimal(row, "ranking_score"),
            "expected_log_growth": _provenance_decimal(row, "expected_log_growth"),
            "robust_expected_log_growth": _provenance_decimal(
                row,
                "robust_expected_log_growth",
            ),
            "quote_integrity": (row.provenance or {}).get("quote_integrity"),
            "classification": row.classification,
            "risk_adjustments": row.risk_adjustments or [],
            "executable_alternatives": row.executable_alternatives or [],
            "provenance": row.provenance or {},
            "explanation": (row.provenance or {}).get("research_explanation"),
            "model_version": row.model_version,
            "policy_version": row.policy_version,
            "recommendation_hash": row.recommendation_hash,
            "slate_date": run.slate_date.isoformat() if row.decision_run_id is not None and run is not None else None,
            "decision_as_of": _iso(run.as_of) if row.decision_run_id is not None and run is not None else None,
            **{
                key: (_iso(value) if isinstance(value, datetime) else value)
                for key, value in timing.items()
            },
            "legs": [
                {
                    "event_id": str(item.canonical_event_id),
                    "market": item.market_type,
                    "side": item.selection_side,
                    "selection": item.selection,
                    "point": _decimal(item.point),
                    "sportsbook": item.sportsbook,
                    "odds": item.american_odds,
                    "fair_probability": _decimal(item.fair_probability),
                    "implied_probability": _decimal(item.implied_probability),
                    "edge": _decimal(item.probability_edge),
                    "ev_per_unit": _decimal(item.ev_per_unit),
                    "model_version": f"{item.model_id}@{item.model_version}",
                    "provenance": item.provenance,
                }
                for item in legs
            ],
        }

    def _open_exposures(self, session: Session, bet: Bet) -> list[OpenExposure]:
        approval = session.scalar(select(BetApproval).where(BetApproval.bet_id == bet.id))
        if bet.bet_kind == "parlay" and approval and approval.recommendation_id:
            legs = list(session.scalars(select(RecommendationLeg).where(RecommendationLeg.recommendation_id == approval.recommendation_id)))
            result: list[OpenExposure] = []
            for item in legs:
                event = session.get(CanonicalEvent, item.canonical_event_id)
                teams: tuple[str, ...] = (event.home_team, event.away_team) if event else ()
                result.append(
                    OpenExposure(
                        str(item.canonical_event_id), teams, item.market_type, item.selection_side,
                        money(bet.stake), "parlay", (f"event:{item.canonical_event_id}",), bet.bet_date,
                    )
                )
            return result
        teams = tuple(item for item in (bet.home_team, bet.away_team) if item)
        event_id = bet.canonical_event_id or bet.provider_event_id or bet.event_name or bet.external_id
        return [OpenExposure(str(event_id), teams, bet.market_type, bet.selection_side or bet.selection, money(bet.stake), bet.bet_kind, (), bet.bet_date)]

    def _validate_approval_risk(
        self,
        session: Session,
        recommendation: Recommendation,
        run: RecommendationDecisionRun,
        stake: Decimal,
        cash: Decimal,
    ) -> None:
        open_bets = list(
            session.scalars(
                select(Bet).where(Bet.portfolio_id == recommendation.portfolio_id, Bet.status == "open")
            )
        )
        reserved = sum((money(item.stake) for item in open_bets), Decimal(0))
        settled = list(
            session.scalars(
                select(Bet)
                .where(Bet.portfolio_id == recommendation.portfolio_id, Bet.status == "settled")
                .order_by(Bet.settled_at, Bet.id)
            )
        )
        running = money(run.starting_bankroll)
        peak = running
        for item in settled:
            running += money(item.realized_pnl or 0)
            peak = max(peak, running)
        equity = cash + reserved
        state_snapshot = PortfolioSnapshot(
            portfolio_id="approval",
            slate_date=run.slate_date,
            starting_bankroll=money(run.starting_bankroll),
            cash=cash,
            reserved_exposure=reserved,
            equity=equity,
            peak_equity=peak,
            realized_pnl=running - money(run.starting_bankroll),
        )
        if portfolio_state(state_snapshot, self.risk_policy).value == "PAUSED":
            raise RecommendationStateError("Portfolio is PAUSED under the current risk policy")
        daily = sum((money(item.stake) for item in open_bets if item.bet_date == run.slate_date), Decimal(0))
        if daily + stake > equity * self.risk_policy.maximum_daily_fraction:
            raise RecommendationStateError("Approval would exceed the daily exposure cap")

        if recommendation.recommendation_kind == "parlay":
            open_parlay = sum(
                (
                    money(item.stake)
                    for item in open_bets
                    if item.bet_date == run.slate_date and item.bet_kind == "parlay"
                ),
                Decimal(0),
            )
            if stake > equity * self.parlay_policy.maximum_parlay_fraction:
                raise RecommendationStateError("Approval would exceed the per-parlay stake cap")
            if open_parlay + stake > equity * self.parlay_policy.maximum_daily_parlay_fraction:
                raise RecommendationStateError("Approval would exceed the daily parlay sleeve cap")
        else:
            per_bet_fraction = (
                self.risk_policy.maximum_core_bet_fraction
                if recommendation.classification == "CORE"
                else self.risk_policy.maximum_opportunistic_bet_fraction
            )
            if stake > min(self.risk_policy.maximum_stake, equity * per_bet_fraction):
                raise RecommendationStateError("Approval would exceed the current per-bet stake cap")

        exposures = [exposure for bet in open_bets for exposure in self._open_exposures(session, bet)]
        targets: list[OpenExposure] = []
        if recommendation.recommendation_kind == "parlay":
            legs = list(
                session.scalars(
                    select(RecommendationLeg).where(RecommendationLeg.recommendation_id == recommendation.id)
                )
            )
            for leg in legs:
                event = session.get(CanonicalEvent, leg.canonical_event_id)
                teams = (event.home_team, event.away_team) if event else ()
                targets.append(
                    OpenExposure(
                        str(leg.canonical_event_id), teams, leg.market_type, leg.selection_side,
                        stake, "parlay", (), run.slate_date,
                    )
                )
        else:
            targets.append(
                OpenExposure(
                    str(recommendation.canonical_event_id),
                    tuple(item for item in (recommendation.home_team, recommendation.away_team) if item),
                    recommendation.market_type,
                    recommendation.selection_side or recommendation.selection,
                    stake,
                    "straight",
                    (),
                    run.slate_date,
                )
            )
        for target in targets:
            proposed_game = sum((item.stake for item in targets if item.event_id == target.event_id), Decimal(0))
            if (
                _exposure(exposures, lambda item, target=target: item.event_id == target.event_id)
                + proposed_game
                > equity * self.risk_policy.maximum_game_fraction
            ):
                raise RecommendationStateError("Approval would exceed a per-game exposure cap")
            if (
                _exposure(exposures, lambda item, target=target: item.event_id == target.event_id)
                + proposed_game
                > equity * self.risk_policy.maximum_correlated_fraction
            ):
                raise RecommendationStateError("Approval would exceed a correlated-exposure cap")
            proposed_market = sum(
                (item.stake for item in targets if item.market_type == target.market_type),
                Decimal(0),
            )
            if (
                _exposure(exposures, lambda item, target=target: item.market_type == target.market_type)
                + proposed_market
                > equity * self.risk_policy.maximum_market_fraction
            ):
                raise RecommendationStateError("Approval would exceed a market-type exposure cap")
            if any(
                item.event_id == target.event_id
                and item.market_type == target.market_type
                and item.selection_side != target.selection_side
                for item in exposures
            ):
                raise RecommendationStateError("Approval would create opposing positions")
            for team in target.teams:
                proposed_team = sum((item.stake for item in targets if team in item.teams), Decimal(0))
                if (
                    _exposure(exposures, lambda item, team=team: team in item.teams)
                    + proposed_team
                    > equity * self.risk_policy.maximum_team_fraction
                ):
                    raise RecommendationStateError("Approval would exceed a per-team exposure cap")

    @staticmethod
    def _cash(session: Session, portfolio_id: UUID) -> Decimal:
        value = session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.portfolio_id == portfolio_id))
        return money(value)


def _alternatives(opportunity: Any) -> list[dict[str, Any]]:
    return [
        {
            "sportsbook": item.sportsbook_key,
            "selection_observation_id": str(item.selection_observation_id),
            "american_odds": item.selection_american_odds,
            "point": str(item.selection_point) if item.selection_point is not None else None,
            "observed_at": _iso(item.selection_observed_at) if item.selection_observed_at else None,
            "no_vig_probability": str(item.selection_probability),
            "snapshot_ids": [str(value) for value in item.snapshot_ids],
        }
        for item in opportunity.book_probabilities
    ]


def _straight_explanation(item: StraightRecommendation) -> str:
    candidate = item.candidate
    opportunity = candidate.opportunity
    return (
        f"{candidate.classification.value if candidate.classification else 'UNCLASSIFIED'} "
        f"market-consensus opportunity at {opportunity.best_sportsbook_name}: "
        f"fair probability {candidate.win_probability}, executable odds "
        f"{opportunity.best_american_odds:+d}, edge {candidate.edge}, and EV per unit "
        f"{candidate.ev_per_unit}; robust expected log-growth score "
        f"{candidate.robust_expected_log_growth} with quote integrity "
        f"{candidate.quote_integrity}; stake is constrained by {item.risk_adjustments}."
    )


def _decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _provenance_decimal(row: Recommendation, key: str) -> float | None:
    value = (row.provenance or {}).get(key)
    return float(Decimal(str(value))) if value is not None else None


def _serialized_recommendation_order(
    item: dict[str, Any],
) -> tuple[str, float, int, int, str]:
    rank = item.get("portfolio_rank")
    decision_as_of = item.get("decision_as_of")
    decision_timestamp = (
        _aware(datetime.fromisoformat(str(decision_as_of))).timestamp()
        if decision_as_of is not None
        else 0.0
    )
    return (
        str(item.get("slate_date") or ""),
        -decision_timestamp,
        0 if item.get("kind") == "straight" else 1,
        int(rank) if rank is not None else 2**31 - 1,
        str(item["recommendation_id"]),
    )


def _iso(value: datetime) -> str:
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _empty_watchlist(as_of: datetime) -> dict[str, Any]:
    return {
        "as_of": _iso(as_of),
        "upcoming_games_analyzed": 0,
        "qualified_recommendations": 0,
        "actionable_recommendations": 0,
        "watchlist_count": 0,
        "watchlist_version": "ncaaf-watchlist-v2",
        "pricing_funnel": {},
        "rejection_counts": {},
        "pricing_pipeline_status": "HEALTHY",
        "pricing_pipeline_status_reason": None,
        "slates": [],
        "items": [],
        "qualified_opportunities": [],
    }


def _normalize_aggregate_funnel_gauges(
    aggregate: Counter[str],
    samples: list[dict[str, int]],
) -> None:
    if not samples:
        return
    snapshot_ages = [item["snapshot_age_seconds"] for item in samples if "snapshot_age_seconds" in item]
    if snapshot_ages:
        aggregate["snapshot_age_seconds"] = min(snapshot_ages)
    for key in ("provider_quote_age_max_seconds", "provider_quote_age_p90_seconds"):
        aggregate[key] = max((item.get(key, 0) for item in samples), default=0)
    minimums = [item["provider_quote_age_min_seconds"] for item in samples if "provider_quote_age_min_seconds" in item]
    if minimums:
        aggregate["provider_quote_age_min_seconds"] = min(minimums)
    for key in ("supported_books_seen", "unsupported_books_seen"):
        aggregate[key] = max((item.get(key, 0) for item in samples), default=0)
    weighted = sorted(
        (
            item.get("provider_quote_age_median_seconds", 0),
            item.get("latest_observations", 0),
        )
        for item in samples
    )
    halfway = sum(weight for _, weight in weighted) / 2
    cumulative = 0
    for value, weight in weighted:
        cumulative += weight
        if cumulative >= halfway:
            aggregate["provider_quote_age_median_seconds"] = value
            break


def _exposure(items: list[OpenExposure], predicate: Any) -> Decimal:
    return sum((item.stake for item in items if predicate(item)), Decimal(0))
