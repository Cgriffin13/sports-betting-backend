from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import require_principal
from app.domain.errors import PortfolioAccessDeniedError
from app.domain.identity import Principal
from app.schemas.portfolios import PortfolioResponse, PortfolioStatsResponse
from app.services.portfolio_service import PortfolioService

router = APIRouter()


@router.get("/portfolio/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(
    portfolio_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    limit: int = 200,
) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    try:
        return service.get_portfolio(principal, portfolio_id, limit)
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None


@router.get("/portfolio/{portfolio_id}/stats", response_model=PortfolioStatsResponse)
def get_portfolio_stats(
    portfolio_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    try:
        return service.get_stats(principal, portfolio_id)
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None
