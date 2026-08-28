from typing import Any

from fastapi import APIRouter, Request

from app.schemas.odds import OddsRequest
from app.services.odds_service import OddsService

router = APIRouter()


@router.post("/odds")
def get_odds(data: OddsRequest, request: Request) -> dict[str, Any]:
    service: OddsService = request.app.state.odds_service
    return service.get_odds(
        requested_date=data.date,
        sports=data.sports,
        markets=data.markets,
        allowed_books=data.allowed_books,
        max_games_per_sport=data.max_games_per_sport,
    )
