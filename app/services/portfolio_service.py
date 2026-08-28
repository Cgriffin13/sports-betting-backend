from __future__ import annotations

from collections.abc import Callable, Mapping
from math import isclose
from typing import Any
from uuid import uuid4

from app.persistence.base import PortfolioRepository
from app.time import utc_now_iso


class PortfolioError(Exception):
    pass


class InsufficientBankrollError(PortfolioError):
    pass


class BetAlreadySettledError(PortfolioError):
    pass


class InvalidLossPayoutError(PortfolioError):
    pass


class BetNotFoundError(PortfolioError):
    pass


class PortfolioService:
    def __init__(
        self,
        repository: PortfolioRepository,
        starting_bankroll: float,
        *,
        clock: Callable[[], str] = utc_now_iso,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._repository = repository
        self._starting_bankroll = starting_bankroll
        self._clock = clock
        self._id_factory = id_factory

    def get_portfolio(self, portfolio_id: str, limit: int = 200) -> dict[str, Any]:
        portfolio = self._repository.get_or_create(portfolio_id)
        return {
            "portfolio_id": portfolio_id,
            "bankroll": portfolio["bankroll"],
            "bets": portfolio["bets"][-limit:],
        }

    def place_bet(self, bet_data: Mapping[str, Any]) -> dict[str, Any]:
        portfolio_id = str(bet_data["portfolio_id"])
        stake = float(bet_data["stake"])
        portfolio = self._repository.get_or_create(portfolio_id)
        if float(portfolio["bankroll"]) < stake:
            raise InsufficientBankrollError

        portfolio["bankroll"] = float(portfolio["bankroll"]) - stake
        bet = dict(bet_data)
        bet_id = self._id_factory()
        bet.update(
            {
                "bet_id": bet_id,
                "result": None,
                "payout": 0.0,
                "created_at": self._clock(),
                "closing_odds": None,
                "closing_book_prob": None,
            }
        )
        portfolio["bets"].append(bet)
        self._repository.save_portfolio(portfolio_id, portfolio)
        return {"message": "Bet recorded", "bet_id": bet_id, "bankroll_after": portfolio["bankroll"]}

    def settle_bet(self, settlement: Mapping[str, Any]) -> dict[str, Any]:
        portfolio_id = str(settlement["portfolio_id"])
        portfolio = self._repository.get_or_create(portfolio_id)
        for bet in portfolio["bets"]:
            if bet["bet_id"] != settlement["bet_id"]:
                continue
            if bet.get("result") in ("win", "loss", "push"):
                raise BetAlreadySettledError

            stake = float(bet.get("stake", 0.0))
            payout = float(settlement["payout"])
            if settlement["result"] == "loss" and not isclose(payout, -stake, abs_tol=0.01):
                raise InvalidLossPayoutError

            bet["result"] = settlement["result"]
            bet["payout"] = payout
            bet["closing_odds"] = settlement.get("closing_odds")
            bet["closing_book_prob"] = settlement.get("closing_book_prob")
            bet["settled_at"] = self._clock()
            portfolio["bankroll"] = float(portfolio["bankroll"]) + stake + payout
            self._repository.save_portfolio(portfolio_id, portfolio)
            return {"message": "Bet result recorded", "bankroll_after": portfolio["bankroll"]}
        raise BetNotFoundError

    def get_stats(self, portfolio_id: str) -> dict[str, Any]:
        portfolio = self._repository.get_or_create(portfolio_id)
        settled = [bet for bet in portfolio["bets"] if bet.get("result") in ("win", "loss", "push")]
        total_staked = sum(float(bet.get("stake", 0.0)) for bet in settled)
        total_profit = sum(float(bet.get("payout", 0.0)) for bet in settled)
        wins = sum(1 for bet in settled if bet["result"] == "win")
        losses = sum(1 for bet in settled if bet["result"] == "loss")
        pushes = sum(1 for bet in settled if bet["result"] == "push")
        count = len(settled)

        bucket_map: dict[tuple[str, str], dict[str, Any]] = {}
        for bet in settled:
            sport = str(bet.get("sport", "UNKNOWN"))
            market_type = str(bet.get("market_type", "UNKNOWN"))
            bucket = bucket_map.setdefault(
                (sport, market_type),
                {
                    "sport": sport,
                    "market_type": market_type,
                    "bets_settled": 0,
                    "wins": 0,
                    "losses": 0,
                    "pushes": 0,
                    "total_staked": 0.0,
                    "total_profit": 0.0,
                },
            )
            bucket["bets_settled"] += 1
            bucket["total_staked"] += float(bet.get("stake", 0.0))
            bucket["total_profit"] += float(bet.get("payout", 0.0))
            result_bucket = {"win": "wins", "loss": "losses", "push": "pushes"}[bet["result"]]
            bucket[result_bucket] += 1

        buckets: list[dict[str, Any]] = []
        for bucket in bucket_map.values():
            bucket_staked = float(bucket["total_staked"])
            bucket["roi"] = float(bucket["total_profit"]) / bucket_staked if bucket_staked > 0 else 0.0
            bucket["hit_rate"] = bucket["wins"] / bucket["bets_settled"] if bucket["bets_settled"] > 0 else 0.0
            buckets.append(bucket)

        bankroll = float(portfolio["bankroll"])
        return {
            "portfolio_id": portfolio_id,
            "starting_bankroll": self._starting_bankroll,
            "current_bankroll": bankroll,
            "net_pnl": bankroll - self._starting_bankroll,
            "overall": {
                "bets_settled": count,
                "wins": wins,
                "losses": losses,
                "pushes": pushes,
                "hit_rate": wins / count if count > 0 else 0.0,
                "total_staked": total_staked,
                "total_profit": total_profit,
                "roi": total_profit / total_staked if total_staked > 0 else 0.0,
            },
            "by_bucket": buckets,
        }
