from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.dependencies import require_principal
from app.domain.errors import (
    BetAlreadySettledError,
    BetNotFoundError,
    IdempotencyConflictError,
    InsufficientBankrollError,
    InvalidLossPayoutError,
    PortfolioAccessDeniedError,
)
from app.domain.identity import Principal
from app.schemas.bets import BetIn, BetRecordedResponse, BetResultIn, BetResultResponse
from app.services.portfolio_service import PortfolioService

router = APIRouter()


@router.post("/bets", response_model=BetRecordedResponse)
def record_bet(
    data: BetIn,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    try:
        return service.place_bet(principal, data.model_dump(), idempotency_key=idempotency_key)
    except InsufficientBankrollError:
        raise HTTPException(status_code=400, detail="Insufficient bankroll for this stake") from None
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None
    except IdempotencyConflictError:
        raise HTTPException(status_code=409, detail="Idempotency key was already used with a different request") from None


@router.post("/bet-result", response_model=BetResultResponse)
def record_bet_result(
    data: BetResultIn,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    try:
        return service.settle_bet(principal, data.model_dump(), idempotency_key=idempotency_key)
    except BetAlreadySettledError:
        raise HTTPException(status_code=400, detail="Bet already settled") from None
    except InvalidLossPayoutError:
        raise HTTPException(status_code=400, detail="Loss payout must equal the negative stake") from None
    except BetNotFoundError:
        raise HTTPException(status_code=404, detail="Bet not found") from None
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None
    except IdempotencyConflictError:
        raise HTTPException(status_code=409, detail="Idempotency key was already used with a different request") from None
