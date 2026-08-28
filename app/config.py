from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    odds_api_key: str | None = None
    starting_bankroll: float = 200.0
    data_dir: Path = Path("data")
    provider_timeout_seconds: float = 12.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.starting_bankroll) or self.starting_bankroll <= 0:
            raise ValueError("STARTING_BANKROLL must be a finite positive number")
        if not math.isfinite(self.provider_timeout_seconds) or self.provider_timeout_seconds <= 0:
            raise ValueError("Provider timeout must be a finite positive number")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        key = os.getenv("ODDS_API_KEY") or None
        raw_bankroll = os.getenv("STARTING_BANKROLL", "200.0")
        try:
            starting_bankroll = float(raw_bankroll)
        except ValueError:
            raise ValueError("STARTING_BANKROLL must be a finite positive number") from None
        return cls(
            odds_api_key=key,
            starting_bankroll=starting_bankroll,
            data_dir=Path(os.getenv("DATA_DIR", "data")),
        )
