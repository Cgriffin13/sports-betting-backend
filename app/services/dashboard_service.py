from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.persistence.dashboard_repository import SqlAlchemyDashboardRepository


class DashboardService:
    def __init__(self, repository: SqlAlchemyDashboardRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def system(self, now: datetime) -> dict[str, Any]:
        latest = self.repository.latest_snapshot_at()
        age = None if latest is None else max(0, int((_utc(now) - _utc(latest)).total_seconds()))
        models = self.repository.list_models()
        retained = [item for item in models if item["status"] == "retained_benchmark"]
        stale = age is None or age > self.settings.market_freshness_seconds
        return {
            "paper_trading": True,
            "league": "NCAAF",
            "system_status": "DEGRADED" if stale or not retained else "OPERATIONAL",
            "model_status": "retained_benchmark" if retained else "unavailable",
            "last_odds_refresh": latest,
            "snapshot_age_seconds": age,
            "stale": stale,
            "next_scheduled_refresh": None,
            "policies": self._safe_policies(),
            "models": models,
        }

    def movement(self, slate_date: date, as_of: datetime) -> dict[str, Any]:
        rows = self.repository.market_movement(slate_date, _utc(as_of))
        events: dict[str, dict[str, Any]] = {}
        snapshots: set[str] = set()
        for row in rows:
            event_id = str(row["event_id"])
            snapshot_id = str(row["snapshot_id"])
            snapshots.add(snapshot_id)
            event = events.setdefault(
                event_id,
                {
                    "event_id": event_id,
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                    "scheduled_start": row["scheduled_start_utc"],
                    # The current provider archive does not label a true opener.
                    "opening_available": False,
                    "points": [],
                },
            )
            event["points"].append(
                {
                    "snapshot_id": snapshot_id,
                    "requested_at": row["requested_at"],
                    "observed_at": row["observed_at"],
                    "sportsbook": row["sportsbook"],
                    "market": row["market_type"],
                    "side": row["selection_side"],
                    "point": float(row["point"]) if row["point"] is not None else None,
                    "american_odds": row["american_odds"],
                    "is_stale": row["is_stale"],
                }
            )
        return {
            "slate_date": slate_date,
            "as_of": _utc(as_of),
            "source_snapshot_count": len(snapshots),
            "events": list(events.values()),
        }

    def _safe_policies(self) -> dict[str, Any]:
        values = {
            "minimum_ev": self.settings.portfolio_minimum_ev,
            "minimum_edge": self.settings.portfolio_minimum_edge,
            "maximum_dispersion": self.settings.portfolio_maximum_dispersion,
            "minimum_books": self.settings.portfolio_minimum_books,
            "freshness_seconds": self.settings.market_freshness_seconds,
            "kelly_fraction": self.settings.portfolio_kelly_fraction,
            "minimum_stake": self.settings.portfolio_minimum_stake,
            "maximum_stake": self.settings.portfolio_maximum_stake,
            "maximum_core_bet_fraction": self.settings.portfolio_maximum_core_bet_fraction,
            "maximum_opportunistic_bet_fraction": self.settings.portfolio_maximum_opportunistic_bet_fraction,
            "maximum_daily_fraction": self.settings.portfolio_maximum_daily_fraction,
            "maximum_game_fraction": self.settings.portfolio_maximum_game_fraction,
            "maximum_team_fraction": self.settings.portfolio_maximum_team_fraction,
            "maximum_market_fraction": self.settings.portfolio_maximum_market_fraction,
            "reduced_risk_drawdown": self.settings.portfolio_reduced_risk_drawdown,
            "paused_drawdown": self.settings.portfolio_paused_drawdown,
            "bankroll_floor_fraction": self.settings.portfolio_bankroll_floor_fraction,
            "unit_fraction": self.settings.portfolio_unit_fraction,
            "parlay_enabled": self.settings.parlay_enabled,
            "parlay_minimum_ev": self.settings.parlay_minimum_ev,
            "parlay_maximum_fraction": self.settings.parlay_maximum_fraction,
            "parlay_daily_fraction": self.settings.parlay_daily_fraction,
        }
        return {key: float(value) if isinstance(value, Decimal) else value for key, value in values.items()}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
