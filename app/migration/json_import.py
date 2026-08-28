from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Bet, BetApproval, BetStateTransition, LedgerEntry, Owner, Portfolio, Settlement
from app.domain.errors import PortfolioAccessDeniedError
from app.domain.identity import Principal
from app.domain.money import money
from app.time import utc_now


def import_json_file(
    path: Path,
    session_factory: sessionmaker[Session],
    principal: Principal,
    starting_capital: Decimal,
) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict) or not isinstance(payload.get("portfolios"), dict):
        raise ValueError("Legacy JSON must contain a portfolios object")

    report: dict[str, Any] = {"portfolios_imported": 0, "bets_imported": 0, "adjustments": []}
    with session_factory() as session, session.begin():
        owner = session.scalar(select(Owner).where(Owner.external_id == principal.external_id))
        if owner is None:
            owner = Owner(external_id=principal.external_id, display_name=principal.display_name, status="active")
            session.add(owner)
            session.flush()

        for external_id, legacy_portfolio in payload["portfolios"].items():
            if not isinstance(legacy_portfolio, dict):
                continue
            portfolio = session.scalar(select(Portfolio).where(Portfolio.external_id == str(external_id)))
            if portfolio is None:
                portfolio = Portfolio(
                    external_id=str(external_id),
                    owner_id=owner.id,
                    starting_capital=money(starting_capital),
                    currency="USD",
                    status="active",
                    created_at=utc_now(),
                )
                session.add(portfolio)
                session.flush()
                session.add(
                    LedgerEntry(
                        portfolio_id=portfolio.id,
                        entry_type="initial_funding",
                        amount=money(starting_capital),
                        reference="initial_funding",
                        metadata_json={"source": "json_import", "source_path": path.name},
                    )
                )
                report["portfolios_imported"] += 1
            elif portfolio.owner_id != owner.id:
                raise PortfolioAccessDeniedError

            legacy_bets = legacy_portfolio.get("bets", [])
            if not isinstance(legacy_bets, list):
                legacy_bets = []
            for index, legacy_bet in enumerate(legacy_bets):
                if not isinstance(legacy_bet, dict):
                    continue
                external_bet_id = str(legacy_bet.get("bet_id") or f"json-{external_id}-{index}")
                existing_bet = session.scalar(select(Bet).where(Bet.external_id == external_bet_id))
                if existing_bet is not None:
                    continue
                stake = money(legacy_bet.get("stake", 0))
                if stake <= 0:
                    continue
                created_at = _parse_datetime(legacy_bet.get("created_at")) or utc_now()
                result = legacy_bet.get("result") if legacy_bet.get("result") in {"win", "loss", "push"} else None
                payout = money(legacy_bet.get("payout", 0))
                bet = Bet(
                    external_id=external_bet_id,
                    portfolio_id=portfolio.id,
                    provider_event_id=legacy_bet.get("provider_event_id"),
                    bet_date=_parse_date(legacy_bet.get("date"), created_at.date()),
                    sport=str(legacy_bet.get("sport", "UNKNOWN")),
                    league=str(legacy_bet.get("league", legacy_bet.get("sport", "UNKNOWN"))),
                    event_name=legacy_bet.get("event_name"),
                    home_team=legacy_bet.get("home_team"),
                    away_team=legacy_bet.get("away_team"),
                    scheduled_start=_parse_datetime(legacy_bet.get("scheduled_start")),
                    market_type=str(legacy_bet.get("market_type", "UNKNOWN")),
                    period=str(legacy_bet.get("period", "full_game")),
                    selection=str(legacy_bet.get("selection", "UNKNOWN")),
                    point=_optional_decimal(legacy_bet.get("point")),
                    sportsbook=str(legacy_bet.get("book", "UNKNOWN")),
                    entry_american_odds=int(legacy_bet.get("odds", -110)),
                    stake=stake,
                    model_probability=_optional_decimal(legacy_bet.get("model_prob")),
                    book_probability=_optional_decimal(legacy_bet.get("book_prob")),
                    probability_edge=_optional_decimal(legacy_bet.get("edge")),
                    ev_per_unit=_optional_decimal(legacy_bet.get("ev_per_1")),
                    approved_at=None,
                    approval_source="legacy_json",
                    placed_at=created_at,
                    created_at=created_at,
                    status="settled" if result else "open",
                    result=result,
                    closing_american_odds=legacy_bet.get("closing_odds"),
                    closing_probability=_optional_decimal(legacy_bet.get("closing_book_prob")),
                    settled_at=_parse_datetime(legacy_bet.get("settled_at")) if result else None,
                    realized_pnl=payout if result else None,
                )
                session.add(bet)
                session.flush()
                session.add(
                    BetApproval(
                        bet_id=bet.id,
                        owner_id=owner.id,
                        source="legacy_json",
                        metadata_json={"explicit_human_approval": None},
                        approved_at=created_at,
                    )
                )
                session.add(
                    BetStateTransition(
                        bet_id=bet.id,
                        from_status=None,
                        to_status="open",
                        source="legacy_json",
                        transitioned_at=created_at,
                    )
                )
                session.add(
                    LedgerEntry(
                        portfolio_id=portfolio.id,
                        entry_type="bet_stake",
                        amount=-stake,
                        related_bet_id=bet.id,
                        reference=f"bet:{external_bet_id}:stake",
                        metadata_json={"source": "json_import"},
                        created_at=created_at,
                    )
                )
                if result:
                    settled_at = bet.settled_at or created_at
                    session.add(
                        BetStateTransition(
                            bet_id=bet.id,
                            from_status="open",
                            to_status="settled",
                            source="legacy_json",
                            metadata_json={"result": result},
                            transitioned_at=settled_at,
                        )
                    )
                    session.add(
                        Settlement(
                            bet_id=bet.id,
                            outcome=result,
                            net_payout=payout,
                            source="legacy_json",
                            closing_american_odds=bet.closing_american_odds,
                            closing_probability=bet.closing_probability,
                            settled_at=settled_at,
                        )
                    )
                    session.add(
                        LedgerEntry(
                            portfolio_id=portfolio.id,
                            entry_type="settlement",
                            amount=stake + payout,
                            related_bet_id=bet.id,
                            reference=f"bet:{external_bet_id}:settlement",
                            metadata_json={"source": "json_import", "result": result},
                            created_at=settled_at,
                        )
                    )
                report["bets_imported"] += 1

            session.flush()
            target_cash = money(legacy_portfolio.get("bankroll", starting_capital))
            derived_cash = money(
                session.scalar(
                    select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                        LedgerEntry.portfolio_id == portfolio.id
                    )
                )
            )
            difference = target_cash - derived_cash
            adjustment_reference = "json_import:reconciliation"
            existing_adjustment = session.scalar(
                select(LedgerEntry).where(
                    LedgerEntry.portfolio_id == portfolio.id,
                    LedgerEntry.reference == adjustment_reference,
                )
            )
            if difference and existing_adjustment is None:
                session.add(
                    LedgerEntry(
                        portfolio_id=portfolio.id,
                        entry_type="adjustment",
                        amount=difference,
                        reference=adjustment_reference,
                        metadata_json={
                            "source": "json_import",
                            "reason": "reconcile legacy current bankroll",
                            "legacy_cash": format(target_cash, "f"),
                        },
                    )
                )
                report["adjustments"].append(
                    {"portfolio_id": portfolio.external_id, "amount": format(difference, "f")}
                )
    return report


def _parse_date(value: Any, default: date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return default


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_decimal(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
