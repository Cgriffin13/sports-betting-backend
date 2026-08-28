from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.schemas.bets import BetIn, BetRecordedResponse, BetResultIn, BetResultResponse
from app.services.portfolio_service import (
    BetAlreadySettledError,
    BetNotFoundError,
    InsufficientBankrollError,
    InvalidLossPayoutError,
    PortfolioService,
)

router = APIRouter()


@router.post("/bets", response_model=BetRecordedResponse)
def record_bet(data: BetIn, request: Request) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    try:
        return service.place_bet(data.model_dump())
    except InsufficientBankrollError:
        raise HTTPException(status_code=400, detail="Insufficient bankroll for this stake") from None


@router.post("/bet-result", response_model=BetResultResponse)
def record_bet_result(data: BetResultIn, request: Request) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    try:
        return service.settle_bet(data.model_dump())
    except BetAlreadySettledError:
        raise HTTPException(status_code=400, detail="Bet already settled") from None
    except InvalidLossPayoutError:
        raise HTTPException(status_code=400, detail="Loss payout must equal the negative stake") from None
    except BetNotFoundError:
        raise HTTPException(status_code=404, detail="Bet not found") from None
