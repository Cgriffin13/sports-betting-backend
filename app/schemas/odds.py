from datetime import date

from pydantic import BaseModel, Field


class OddsRequest(BaseModel):
    date: date
    sports: list[str] | None = None
    markets: list[str] | None = None
    allowed_books: list[str] | None = None
    max_games_per_sport: int = Field(default=50, ge=1, le=200)
