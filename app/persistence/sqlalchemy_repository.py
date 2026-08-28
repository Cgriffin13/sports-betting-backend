from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Bet,
    BetApproval,
    BetStateTransition,
    IdempotencyRecord,
    LedgerEntry,
    Owner,
    Portfolio,
    Settlement,
)
from app.domain.errors import (
    BetAlreadySettledError,
    BetNotFoundError,
    IdempotencyConflictError,
    InsufficientBankrollError,
    InvalidLossPayoutError,
    PortfolioAccessDeniedError,
)
from app.domain.identity import Principal
from app.domain.money import money, money_json
from app.time import utc_now


class SqlAlchemyPortfolioRepository:
    """Transactional relational repository for portfolio aggregates and their ledger."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        starting_capital: Decimal,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._starting_capital = money(starting_capital)
        self._clock = clock
        self._id_factory = id_factory

    def get_portfolio(self, principal: Principal, portfolio_id: str, limit: int = 200) -> dict[str, Any]:
        owner_id = self.ensure_owner(principal)
        with self._session_factory() as session, session.begin():
            self._lock_owner(session, owner_id)
            portfolio = self._load_or_create_portfolio(session, owner_id, portfolio_id)
            return self._portfolio_response(session, portfolio, limit)

    def place_bet(
        self,
        principal: Principal,
        bet_data: Mapping[str, Any],
        *,
        idempotency_key: str | None,
        request_hash: str,
    ) -> dict[str, Any]:
        owner_id = self.ensure_owner(principal)

        def operation(session: Session) -> dict[str, Any]:
            self._lock_owner(session, owner_id)
            external_portfolio_id = str(bet_data["portfolio_id"])
            portfolio = self._load_or_create_portfolio(session, owner_id, external_portfolio_id, lock=True)
            stake = money(bet_data["stake"])
            cash = self._cash(session, portfolio.id)
            if cash < stake:
                raise InsufficientBankrollError

            now = self._clock()
            bet_uuid = self._id_factory()
            bet = Bet(
                id=bet_uuid,
                external_id=str(bet_uuid),
                portfolio_id=portfolio.id,
                provider_event_id=self._optional_string(bet_data.get("provider_event_id")),
                bet_date=self._as_date(bet_data["date"]),
                sport=str(bet_data["sport"]),
                league=str(bet_data["league"]),
                event_name=self._optional_string(bet_data.get("event_name")),
                home_team=self._optional_string(bet_data.get("home_team")),
                away_team=self._optional_string(bet_data.get("away_team")),
                scheduled_start=self._optional_datetime(bet_data.get("scheduled_start")),
                market_type=str(bet_data["market_type"]),
                period=str(bet_data.get("period") or "full_game"),
                selection=str(bet_data["selection"]),
                point=self._optional_decimal(bet_data.get("point")),
                sportsbook=str(bet_data["book"]),
                entry_american_odds=int(bet_data["odds"]),
                stake=stake,
                model_probability=self._optional_decimal(bet_data.get("model_prob")),
                book_probability=self._optional_decimal(bet_data.get("book_prob")),
                consensus_probability=self._optional_decimal(bet_data.get("consensus_prob")),
                fair_probability=self._optional_decimal(bet_data.get("fair_prob")),
                probability_edge=self._optional_decimal(bet_data.get("edge")),
                ev_per_unit=self._optional_decimal(bet_data.get("ev_per_1")),
                recommendation_version=self._optional_string(bet_data.get("recommendation_version")),
                model_version=self._optional_string(bet_data.get("model_version")),
                policy_version=self._optional_string(bet_data.get("policy_version")),
                approved_at=now,
                approval_source="manual_api",
                placed_at=now,
                created_at=now,
                status="open",
            )
            session.add(bet)
            session.flush()
            session.add_all(
                [
                    BetApproval(
                        id=self._id_factory(),
                        bet_id=bet.id,
                        owner_id=owner_id,
                        source="manual_api",
                        metadata_json={"explicit_human_approval": True},
                        approved_at=now,
                    ),
                    BetStateTransition(
                        id=self._id_factory(),
                        bet_id=bet.id,
                        from_status=None,
                        to_status="open",
                        source="manual_api",
                        transitioned_at=now,
                    ),
                ]
            )
            session.add(
                LedgerEntry(
                    id=self._id_factory(),
                    portfolio_id=portfolio.id,
                    entry_type="bet_stake",
                    amount=-stake,
                    related_bet_id=bet.id,
                    reference=f"bet:{bet.external_id}:stake",
                    idempotency_key=idempotency_key,
                    metadata_json={"purpose": "reserve paper-bet stake"},
                    created_at=now,
                )
            )
            session.flush()
            return {
                "message": "Bet recorded",
                "bet_id": bet.external_id,
                "bankroll_after": money_json(self._cash(session, portfolio.id)),
            }

        return self._execute_mutation(owner_id, "/bets", idempotency_key, request_hash, operation)

    def settle_bet(
        self,
        principal: Principal,
        settlement: Mapping[str, Any],
        *,
        idempotency_key: str | None,
        request_hash: str,
    ) -> dict[str, Any]:
        owner_id = self.ensure_owner(principal)

        def operation(session: Session) -> dict[str, Any]:
            self._lock_owner(session, owner_id)
            portfolio = self._load_or_create_portfolio(
                session, owner_id, str(settlement["portfolio_id"]), lock=True
            )
            bet = session.scalar(
                select(Bet)
                .where(Bet.external_id == str(settlement["bet_id"]), Bet.portfolio_id == portfolio.id)
                .with_for_update()
            )
            if bet is None:
                raise BetNotFoundError
            if bet.status == "settled" or bet.result in ("win", "loss", "push"):
                raise BetAlreadySettledError

            payout = money(settlement["payout"])
            if settlement["result"] == "loss" and payout != -money(bet.stake):
                raise InvalidLossPayoutError

            now = self._clock()
            closing_probability = self._optional_decimal(settlement.get("closing_book_prob"))
            settlement_record = Settlement(
                id=self._id_factory(),
                bet_id=bet.id,
                outcome=str(settlement["result"]),
                net_payout=payout,
                source=str(settlement.get("source") or "manual_api"),
                closing_american_odds=settlement.get("closing_odds"),
                closing_probability=closing_probability,
                settled_at=now,
            )
            session.add(settlement_record)
            bet.status = "settled"
            bet.result = str(settlement["result"])
            bet.closing_american_odds = settlement.get("closing_odds")
            bet.closing_probability = closing_probability
            bet.settled_at = now
            bet.realized_pnl = payout
            session.add(
                BetStateTransition(
                    id=self._id_factory(),
                    bet_id=bet.id,
                    from_status="open",
                    to_status="settled",
                    source=settlement_record.source,
                    metadata_json={"result": bet.result},
                    transitioned_at=now,
                )
            )
            settlement_cash = money(bet.stake) + payout
            session.add(
                LedgerEntry(
                    id=self._id_factory(),
                    portfolio_id=portfolio.id,
                    entry_type="settlement",
                    amount=settlement_cash,
                    related_bet_id=bet.id,
                    reference=f"bet:{bet.external_id}:settlement",
                    idempotency_key=idempotency_key,
                    metadata_json={"result": bet.result, "source": settlement_record.source},
                    created_at=now,
                )
            )
            session.flush()
            return {
                "message": "Bet result recorded",
                "bankroll_after": money_json(self._cash(session, portfolio.id)),
            }

        return self._execute_mutation(owner_id, "/bet-result", idempotency_key, request_hash, operation)

    def get_stats(self, principal: Principal, portfolio_id: str) -> dict[str, Any]:
        owner_id = self.ensure_owner(principal)
        with self._session_factory() as session, session.begin():
            portfolio = self._load_or_create_portfolio(session, owner_id, portfolio_id)
            bets = list(
                session.scalars(select(Bet).where(Bet.portfolio_id == portfolio.id, Bet.status == "settled"))
            )
            cash = self._cash(session, portfolio.id)
            reserved = self._reserved(session, portfolio.id)
            equity = cash + reserved
            realized = sum((money(bet.realized_pnl or Decimal("0")) for bet in bets), Decimal("0.00"))
            total_staked = sum((money(bet.stake) for bet in bets), Decimal("0.00"))
            wins = sum(1 for bet in bets if bet.result == "win")
            losses = sum(1 for bet in bets if bet.result == "loss")
            pushes = sum(1 for bet in bets if bet.result == "push")
            count = len(bets)

            buckets: dict[tuple[str, str], dict[str, Any]] = {}
            for bet in bets:
                bucket = buckets.setdefault(
                    (bet.sport, bet.market_type),
                    {
                        "sport": bet.sport,
                        "market_type": bet.market_type,
                        "bets_settled": 0,
                        "wins": 0,
                        "losses": 0,
                        "pushes": 0,
                        "total_staked": Decimal("0.00"),
                        "total_profit": Decimal("0.00"),
                    },
                )
                bucket["bets_settled"] += 1
                bucket["total_staked"] += money(bet.stake)
                bucket["total_profit"] += money(bet.realized_pnl or Decimal("0"))
                result_key = (
                    {"win": "wins", "loss": "losses", "push": "pushes"}.get(bet.result)
                    if bet.result is not None
                    else None
                )
                if result_key:
                    bucket[result_key] += 1

            serialized_buckets: list[dict[str, Any]] = []
            for bucket in buckets.values():
                bucket_staked = money(bucket["total_staked"])
                serialized_buckets.append(
                    {
                        **bucket,
                        "total_staked": money_json(bucket_staked),
                        "total_profit": money_json(bucket["total_profit"]),
                        "roi": float(bucket["total_profit"] / bucket_staked) if bucket_staked else 0.0,
                        "hit_rate": bucket["wins"] / bucket["bets_settled"],
                    }
                )

            return {
                "portfolio_id": portfolio.external_id,
                "starting_bankroll": money_json(portfolio.starting_capital),
                "current_bankroll": money_json(cash),
                "cash": money_json(cash),
                "reserved_stake": money_json(reserved),
                "open_exposure": money_json(reserved),
                "equity": money_json(equity),
                "realized_pnl": money_json(realized),
                "net_pnl": money_json(equity - money(portfolio.starting_capital)),
                "overall": {
                    "bets_settled": count,
                    "wins": wins,
                    "losses": losses,
                    "pushes": pushes,
                    "hit_rate": wins / count if count else 0.0,
                    "total_staked": money_json(total_staked),
                    "total_profit": money_json(realized),
                    "roi": float(realized / total_staked) if total_staked else 0.0,
                },
                "by_bucket": serialized_buckets,
            }

    def ensure_owner(self, principal: Principal) -> UUID:
        try:
            with self._session_factory() as session, session.begin():
                owner = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
                if owner:
                    return owner.id
                owner = Owner(
                    id=self._id_factory(),
                    external_id=principal.external_id,
                    display_name=principal.display_name,
                    status="active",
                    created_at=self._clock(),
                )
                session.add(owner)
                session.flush()
                return owner.id
        except IntegrityError:
            with self._session_factory() as session:
                existing = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
                if existing is None:
                    raise
                return existing.id

    def _execute_mutation(
        self,
        owner_id: UUID,
        endpoint: str,
        idempotency_key: str | None,
        request_hash: str,
        operation: Callable[[Session], dict[str, Any]],
    ) -> dict[str, Any]:
        if idempotency_key is None:
            with self._session_factory() as session, session.begin():
                return operation(session)

        try:
            with self._session_factory() as session, session.begin():
                record = IdempotencyRecord(
                    id=self._id_factory(),
                    owner_id=owner_id,
                    endpoint=endpoint,
                    key=idempotency_key,
                    request_hash=request_hash,
                    created_at=self._clock(),
                )
                session.add(record)
                session.flush()
                response = operation(session)
                record.response_status = 200
                record.response_body = response
                return response
        except IntegrityError:
            with self._session_factory() as session:
                existing = session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.owner_id == owner_id,
                        IdempotencyRecord.endpoint == endpoint,
                        IdempotencyRecord.key == idempotency_key,
                    )
                )
                if existing is None:
                    raise
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError
                if existing.response_body is None:
                    raise RuntimeError("Idempotency record committed without a response")
                return dict(existing.response_body)

    def _load_or_create_portfolio(
        self,
        session: Session,
        owner_id: UUID,
        external_id: str,
        *,
        lock: bool = False,
    ) -> Portfolio:
        statement = select(Portfolio).where(Portfolio.external_id == external_id)
        if lock:
            statement = statement.with_for_update()
        portfolio = session.scalar(statement)
        if portfolio:
            if portfolio.owner_id != owner_id:
                raise PortfolioAccessDeniedError
            return portfolio

        now = self._clock()
        portfolio = Portfolio(
            id=self._id_factory(),
            external_id=external_id,
            owner_id=owner_id,
            starting_capital=self._starting_capital,
            currency="USD",
            status="active",
            created_at=now,
        )
        session.add(portfolio)
        session.flush()
        session.add(
            LedgerEntry(
                id=self._id_factory(),
                portfolio_id=portfolio.id,
                entry_type="initial_funding",
                amount=self._starting_capital,
                reference="initial_funding",
                metadata_json={"source": "portfolio_creation"},
                created_at=now,
            )
        )
        session.flush()
        return portfolio

    @staticmethod
    def _lock_owner(session: Session, owner_id: UUID) -> None:
        session.scalar(select(Owner.id).where(Owner.id == owner_id).with_for_update())

    @staticmethod
    def _cash(session: Session, portfolio_id: UUID) -> Decimal:
        value = session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.portfolio_id == portfolio_id)
        )
        return money(value)

    @staticmethod
    def _reserved(session: Session, portfolio_id: UUID) -> Decimal:
        value = session.scalar(
            select(func.coalesce(func.sum(Bet.stake), 0)).where(
                Bet.portfolio_id == portfolio_id, Bet.status == "open"
            )
        )
        return money(value)

    def _portfolio_response(self, session: Session, portfolio: Portfolio, limit: int) -> dict[str, Any]:
        descending = list(
            session.scalars(
                select(Bet)
                .where(Bet.portfolio_id == portfolio.id)
                .order_by(Bet.created_at.desc(), Bet.external_id.desc())
                .limit(limit)
            )
        )
        bets = [self._serialize_bet(session, bet, portfolio.external_id) for bet in reversed(descending)]
        cash = self._cash(session, portfolio.id)
        reserved = self._reserved(session, portfolio.id)
        realized = session.scalar(
            select(func.coalesce(func.sum(Bet.realized_pnl), 0)).where(
                Bet.portfolio_id == portfolio.id, Bet.status == "settled"
            )
        )
        return {
            "portfolio_id": portfolio.external_id,
            "bankroll": money_json(cash),
            "cash": money_json(cash),
            "reserved_stake": money_json(reserved),
            "open_exposure": money_json(reserved),
            "equity": money_json(cash + reserved),
            "realized_pnl": money_json(money(realized)),
            "currency": portfolio.currency,
            "bets": bets,
        }

    def _serialize_bet(self, session: Session, bet: Bet, portfolio_external_id: str) -> dict[str, Any]:
        settlement = session.scalar(select(Settlement).where(Settlement.bet_id == bet.id))
        result: dict[str, Any] = {
            "portfolio_id": portfolio_external_id,
            "date": bet.bet_date.isoformat(),
            "sport": bet.sport,
            "league": bet.league,
            "market_type": bet.market_type,
            "selection": bet.selection,
            "book": bet.sportsbook,
            "odds": bet.entry_american_odds,
            "stake": money_json(bet.stake),
            "model_prob": self._decimal_json(bet.model_probability),
            "book_prob": self._decimal_json(bet.book_probability),
            "edge": self._decimal_json(bet.probability_edge),
            "ev_per_1": self._decimal_json(bet.ev_per_unit),
            "bet_id": bet.external_id,
            "result": bet.result,
            "payout": money_json(settlement.net_payout) if settlement else 0.0,
            "created_at": self._datetime_iso(bet.created_at),
            "closing_odds": bet.closing_american_odds,
            "closing_book_prob": self._decimal_json(bet.closing_probability),
            "status": bet.status,
            "provider_event_id": bet.provider_event_id,
            "event_name": bet.event_name,
            "home_team": bet.home_team,
            "away_team": bet.away_team,
            "scheduled_start": self._datetime_iso(bet.scheduled_start),
            "period": bet.period,
            "point": self._decimal_json(bet.point),
            "consensus_prob": self._decimal_json(bet.consensus_probability),
            "fair_prob": self._decimal_json(bet.fair_probability),
            "recommendation_version": bet.recommendation_version,
            "model_version": bet.model_version,
            "policy_version": bet.policy_version,
            "approved_at": self._datetime_iso(bet.approved_at),
            "approval_source": bet.approval_source,
            "placed_at": self._datetime_iso(bet.placed_at),
            "settled_at": self._datetime_iso(bet.settled_at),
            "settlement_source": settlement.source if settlement else None,
            "realized_pnl": self._decimal_json(bet.realized_pnl),
        }
        return result

    @staticmethod
    def _optional_decimal(value: Any) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    @staticmethod
    def _decimal_json(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _as_date(value: Any) -> date:
        return value if isinstance(value, date) else date.fromisoformat(str(value))

    @staticmethod
    def _optional_datetime(value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _datetime_iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
