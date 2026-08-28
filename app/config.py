from __future__ import annotations

import math
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    odds_api_key: str | None = None
    database_url: str = "sqlite+pysqlite:///:memory:"
    app_api_key: str = "test-only-api-key"
    app_owner_id: str = "default"
    app_owner_name: str = "Default Owner"
    starting_bankroll: Decimal = Decimal("200.00")
    data_dir: Path = Path("data")
    provider_timeout_seconds: float = 12.0

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
            database_url=database_url,
            app_api_key=app_api_key,
            app_owner_id=os.getenv("APP_OWNER_ID", "default"),
            app_owner_name=os.getenv("APP_OWNER_NAME", "Default Owner"),
            starting_bankroll=starting_bankroll,
            data_dir=Path(os.getenv("DATA_DIR", "data")),
        )
