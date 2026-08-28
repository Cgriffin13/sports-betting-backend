from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import require_principal
from app.domain.identity import Principal
from app.schemas.odds import OddsRequest
from app.services.odds_service import OddsService

router = APIRouter()


@router.post("/odds")
def get_odds(
    data: OddsRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
) -> dict[str, Any]:
    del principal
    service: OddsService = request.app.state.odds_service
    return service.get_odds(
        requested_date=data.date,
        sports=data.sports,
        markets=data.markets,
        allowed_books=data.allowed_books,
        max_games_per_sport=data.max_games_per_sport,
    )
