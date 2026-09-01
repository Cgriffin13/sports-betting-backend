from __future__ import annotations

import math
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv


def _decimal_environment(name: str, default: str) -> Decimal:
    try:
        return Decimal(os.getenv(name, default))
    except InvalidOperation:
        raise ValueError(f"{name} must be a finite decimal number") from None


@dataclass(frozen=True, slots=True)
class Settings:
    odds_api_key: str | None = None
    cfbd_api_key: str | None = None
    database_url: str = "sqlite+pysqlite:///:memory:"
    app_api_key: str = "test-only-api-key"
    app_owner_id: str = "default"
    app_owner_name: str = "Default Owner"
    starting_bankroll: Decimal = Decimal("200.00")
    data_dir: Path = Path("data")
    ncaaf_artifact_dir: Path = Path(".ncaaf-data")
    cfbd_timeout_seconds: float = 30.0
    provider_timeout_seconds: float = 12.0
    provider_max_retries: int = 2
    provider_backoff_seconds: float = 0.25
    provider_cache_ttl_seconds: float = 15.0
    provider_low_quota_threshold: int = 10
    market_freshness_seconds: int = 120
    pricing_minimum_books: int = 2
    pricing_minimum_ev: Decimal = Decimal("0.01")
    pricing_minimum_probability_edge: Decimal = Decimal("0.005")
    pricing_outlier_threshold: Decimal = Decimal("0.03")
    pricing_maximum_dispersion: Decimal = Decimal("0.08")
    pricing_supported_books: tuple[str, ...] = ("draftkings", "fanduel", "betmgm")
    portfolio_minimum_ev: Decimal = Decimal("0.015")
    portfolio_minimum_edge: Decimal = Decimal("0.0075")
    portfolio_maximum_dispersion: Decimal = Decimal("0.06")
    portfolio_minimum_books: int = 2
    portfolio_kelly_fraction: Decimal = Decimal("0.25")
    portfolio_minimum_stake: Decimal = Decimal("1.00")
    portfolio_maximum_stake: Decimal = Decimal("50.00")
    portfolio_maximum_core_bet_fraction: Decimal = Decimal("0.02")
    portfolio_maximum_opportunistic_bet_fraction: Decimal = Decimal("0.01")
    portfolio_maximum_daily_fraction: Decimal = Decimal("0.08")
    portfolio_maximum_game_fraction: Decimal = Decimal("0.04")
    portfolio_maximum_team_fraction: Decimal = Decimal("0.05")
    portfolio_maximum_market_fraction: Decimal = Decimal("0.05")
    portfolio_maximum_correlated_fraction: Decimal = Decimal("0.04")
    portfolio_unit_fraction: Decimal = Decimal("0.04")
    portfolio_reduced_risk_drawdown: Decimal = Decimal("0.10")
    portfolio_paused_drawdown: Decimal = Decimal("0.20")
    portfolio_bankroll_floor_fraction: Decimal = Decimal("0.50")
    portfolio_core_minimum_ev: Decimal = Decimal("0.03")
    portfolio_core_minimum_edge: Decimal = Decimal("0.015")
    parlay_enabled: bool = True
    parlay_minimum_ev: Decimal = Decimal("0.05")
    parlay_kelly_fraction: Decimal = Decimal("0.10")
    parlay_maximum_fraction: Decimal = Decimal("0.005")
    parlay_daily_fraction: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        try:
            starting_bankroll = (
                self.starting_bankroll
                if isinstance(self.starting_bankroll, Decimal)
                else Decimal(str(self.starting_bankroll))
            )
        except InvalidOperation:
            raise ValueError("STARTING_BANKROLL must be a finite positive number") from None
        object.__setattr__(self, "starting_bankroll", starting_bankroll)
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL is required")
        if not self.app_api_key.strip():
            raise ValueError("APP_API_KEY is required")
        if not self.app_owner_id.strip():
            raise ValueError("APP_OWNER_ID is required")
        if not starting_bankroll.is_finite() or starting_bankroll <= 0:
            raise ValueError("STARTING_BANKROLL must be a finite positive number")
        if not math.isfinite(self.provider_timeout_seconds) or self.provider_timeout_seconds <= 0:
            raise ValueError("Provider timeout must be a finite positive number")
        if not math.isfinite(self.cfbd_timeout_seconds) or self.cfbd_timeout_seconds <= 0:
            raise ValueError("CFBD timeout must be a finite positive number")
        if self.provider_max_retries < 0 or self.provider_max_retries > 5:
            raise ValueError("Provider max retries must be between 0 and 5")
        if not math.isfinite(self.provider_backoff_seconds) or self.provider_backoff_seconds < 0:
            raise ValueError("Provider backoff must be finite and nonnegative")
        if not math.isfinite(self.provider_cache_ttl_seconds) or self.provider_cache_ttl_seconds < 0:
            raise ValueError("Provider cache TTL must be finite and nonnegative")
        if self.provider_low_quota_threshold < 0:
            raise ValueError("Provider low quota threshold must be nonnegative")
        if self.market_freshness_seconds <= 0:
            raise ValueError("Market freshness threshold must be positive")
        if self.pricing_minimum_books < 2:
            raise ValueError("Pricing minimum books must be at least 2")
        pricing_decimals = (
            ("PRICING_MINIMUM_EV", self.pricing_minimum_ev),
            ("PRICING_MINIMUM_PROBABILITY_EDGE", self.pricing_minimum_probability_edge),
            ("PRICING_OUTLIER_THRESHOLD", self.pricing_outlier_threshold),
            ("PRICING_MAXIMUM_DISPERSION", self.pricing_maximum_dispersion),
        )
        for name, value in pricing_decimals:
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
        if self.pricing_minimum_ev < 0 or self.pricing_minimum_probability_edge < 0:
            raise ValueError("Pricing qualification thresholds must be nonnegative")
        if self.pricing_outlier_threshold < 0 or self.pricing_maximum_dispersion < 0:
            raise ValueError("Pricing dispersion thresholds must be nonnegative")
        if self.pricing_outlier_threshold > 1 or self.pricing_maximum_dispersion > 1:
            raise ValueError("Pricing dispersion thresholds cannot exceed 1")
        if self.pricing_maximum_dispersion < self.pricing_outlier_threshold:
            raise ValueError("Pricing maximum dispersion cannot be below the outlier threshold")
        if not self.pricing_supported_books or any(not book.strip() for book in self.pricing_supported_books):
            raise ValueError("PRICING_SUPPORTED_BOOKS must contain at least one non-empty book key")
        portfolio_decimals = (
            self.portfolio_minimum_ev,
            self.portfolio_minimum_edge,
            self.portfolio_maximum_dispersion,
            self.portfolio_kelly_fraction,
            self.portfolio_minimum_stake,
            self.portfolio_maximum_stake,
            self.portfolio_maximum_core_bet_fraction,
            self.portfolio_maximum_opportunistic_bet_fraction,
            self.portfolio_maximum_daily_fraction,
            self.portfolio_maximum_game_fraction,
            self.portfolio_maximum_team_fraction,
            self.portfolio_maximum_market_fraction,
            self.portfolio_maximum_correlated_fraction,
            self.portfolio_unit_fraction,
            self.portfolio_reduced_risk_drawdown,
            self.portfolio_paused_drawdown,
            self.portfolio_bankroll_floor_fraction,
            self.portfolio_core_minimum_ev,
            self.portfolio_core_minimum_edge,
            self.parlay_minimum_ev,
            self.parlay_kelly_fraction,
            self.parlay_maximum_fraction,
            self.parlay_daily_fraction,
        )
        if any(not value.is_finite() or value < 0 for value in portfolio_decimals):
            raise ValueError("Portfolio and parlay policy values must be finite and nonnegative")
        if self.portfolio_kelly_fraction >= 1 or self.parlay_kelly_fraction >= 1:
            raise ValueError("Full Kelly is prohibited")
        if self.parlay_maximum_fraction > Decimal("0.0075"):
            raise ValueError("Parlay maximum fraction cannot exceed 0.75%")
        if self.portfolio_minimum_books < 2:
            raise ValueError("Portfolio minimum books must be at least two")
        if self.portfolio_minimum_stake <= 0 or self.portfolio_maximum_stake < self.portfolio_minimum_stake:
            raise ValueError("Portfolio stake boundaries must be positive and ordered")
        if self.portfolio_core_minimum_ev < self.portfolio_minimum_ev:
            raise ValueError("CORE EV threshold cannot be below the qualification threshold")
        if self.portfolio_core_minimum_edge < self.portfolio_minimum_edge:
            raise ValueError("CORE edge threshold cannot be below the qualification threshold")
        if self.portfolio_reduced_risk_drawdown >= self.portfolio_paused_drawdown:
            raise ValueError("Reduced-risk drawdown must be below paused drawdown")
        if self.parlay_daily_fraction < self.parlay_maximum_fraction:
            raise ValueError("Daily parlay sleeve cannot be below the per-parlay cap")
        bounded_fractions = (
            self.portfolio_minimum_edge,
            self.portfolio_maximum_dispersion,
            self.portfolio_maximum_core_bet_fraction,
            self.portfolio_maximum_opportunistic_bet_fraction,
            self.portfolio_maximum_daily_fraction,
            self.portfolio_maximum_game_fraction,
            self.portfolio_maximum_team_fraction,
            self.portfolio_maximum_market_fraction,
            self.portfolio_maximum_correlated_fraction,
            self.portfolio_unit_fraction,
            self.portfolio_reduced_risk_drawdown,
            self.portfolio_paused_drawdown,
            self.portfolio_bankroll_floor_fraction,
            self.portfolio_core_minimum_edge,
            self.parlay_maximum_fraction,
            self.parlay_daily_fraction,
        )
        if any(value > 1 for value in bounded_fractions):
            raise ValueError("Portfolio probability and exposure fractions cannot exceed one")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        key = os.getenv("ODDS_API_KEY") or None
        database_url = os.getenv("DATABASE_URL")
        app_api_key = os.getenv("APP_API_KEY")
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        if not app_api_key:
            raise ValueError("APP_API_KEY is required")
        raw_bankroll = os.getenv("STARTING_BANKROLL", "200.0")
        try:
            starting_bankroll = Decimal(raw_bankroll)
        except InvalidOperation:
            raise ValueError("STARTING_BANKROLL must be a finite positive number") from None
        return cls(
            odds_api_key=key,
            cfbd_api_key=os.getenv("CFBD_API_KEY") or None,
            database_url=database_url,
            app_api_key=app_api_key,
            app_owner_id=os.getenv("APP_OWNER_ID", "default"),
            app_owner_name=os.getenv("APP_OWNER_NAME", "Default Owner"),
            starting_bankroll=starting_bankroll,
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            ncaaf_artifact_dir=Path(os.getenv("NCAAF_ARTIFACT_DIR", ".ncaaf-data")),
            cfbd_timeout_seconds=float(os.getenv("CFBD_TIMEOUT_SECONDS", "30")),
            provider_timeout_seconds=float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "12.0")),
            provider_max_retries=int(os.getenv("PROVIDER_MAX_RETRIES", "2")),
            provider_backoff_seconds=float(os.getenv("PROVIDER_BACKOFF_SECONDS", "0.25")),
            provider_cache_ttl_seconds=float(os.getenv("PROVIDER_CACHE_TTL_SECONDS", "15.0")),
            provider_low_quota_threshold=int(os.getenv("PROVIDER_LOW_QUOTA_THRESHOLD", "10")),
            market_freshness_seconds=int(os.getenv("MARKET_FRESHNESS_SECONDS", "120")),
            pricing_minimum_books=int(os.getenv("PRICING_MINIMUM_BOOKS", "2")),
            pricing_minimum_ev=_decimal_environment("PRICING_MINIMUM_EV", "0.01"),
            pricing_minimum_probability_edge=_decimal_environment(
                "PRICING_MINIMUM_PROBABILITY_EDGE", "0.005"
            ),
            pricing_outlier_threshold=_decimal_environment("PRICING_OUTLIER_THRESHOLD", "0.03"),
            pricing_maximum_dispersion=_decimal_environment("PRICING_MAXIMUM_DISPERSION", "0.08"),
            pricing_supported_books=tuple(
                book.strip().lower()
                for book in os.getenv("PRICING_SUPPORTED_BOOKS", "draftkings,fanduel,betmgm").split(",")
                if book.strip()
            ),
            portfolio_minimum_ev=_decimal_environment("PORTFOLIO_MINIMUM_EV", "0.015"),
            portfolio_minimum_edge=_decimal_environment("PORTFOLIO_MINIMUM_EDGE", "0.0075"),
            portfolio_maximum_dispersion=_decimal_environment("PORTFOLIO_MAXIMUM_DISPERSION", "0.06"),
            portfolio_minimum_books=int(os.getenv("PORTFOLIO_MINIMUM_BOOKS", "2")),
            portfolio_kelly_fraction=_decimal_environment("PORTFOLIO_KELLY_FRACTION", "0.25"),
            portfolio_minimum_stake=_decimal_environment("PORTFOLIO_MINIMUM_STAKE", "1.00"),
            portfolio_maximum_stake=_decimal_environment("PORTFOLIO_MAXIMUM_STAKE", "50.00"),
            portfolio_maximum_core_bet_fraction=_decimal_environment("PORTFOLIO_MAXIMUM_CORE_BET_FRACTION", "0.02"),
            portfolio_maximum_opportunistic_bet_fraction=_decimal_environment("PORTFOLIO_MAXIMUM_OPPORTUNISTIC_BET_FRACTION", "0.01"),
            portfolio_maximum_daily_fraction=_decimal_environment("PORTFOLIO_MAXIMUM_DAILY_FRACTION", "0.08"),
            portfolio_maximum_game_fraction=_decimal_environment("PORTFOLIO_MAXIMUM_GAME_FRACTION", "0.04"),
            portfolio_maximum_team_fraction=_decimal_environment("PORTFOLIO_MAXIMUM_TEAM_FRACTION", "0.05"),
            portfolio_maximum_market_fraction=_decimal_environment("PORTFOLIO_MAXIMUM_MARKET_FRACTION", "0.05"),
            portfolio_maximum_correlated_fraction=_decimal_environment("PORTFOLIO_MAXIMUM_CORRELATED_FRACTION", "0.04"),
            portfolio_unit_fraction=_decimal_environment("PORTFOLIO_UNIT_FRACTION", "0.04"),
            portfolio_reduced_risk_drawdown=_decimal_environment("PORTFOLIO_REDUCED_RISK_DRAWDOWN", "0.10"),
            portfolio_paused_drawdown=_decimal_environment("PORTFOLIO_PAUSED_DRAWDOWN", "0.20"),
            portfolio_bankroll_floor_fraction=_decimal_environment("PORTFOLIO_BANKROLL_FLOOR_FRACTION", "0.50"),
            portfolio_core_minimum_ev=_decimal_environment("PORTFOLIO_CORE_MINIMUM_EV", "0.03"),
            portfolio_core_minimum_edge=_decimal_environment("PORTFOLIO_CORE_MINIMUM_EDGE", "0.015"),
            parlay_enabled=os.getenv("PARLAY_ENABLED", "true").strip().lower() in {"1", "true", "yes"},
            parlay_minimum_ev=_decimal_environment("PARLAY_MINIMUM_EV", "0.05"),
            parlay_kelly_fraction=_decimal_environment("PARLAY_KELLY_FRACTION", "0.10"),
            parlay_maximum_fraction=_decimal_environment("PARLAY_MAXIMUM_FRACTION", "0.005"),
            parlay_daily_fraction=_decimal_environment("PARLAY_DAILY_FRACTION", "0.01"),
        )
