from typing import Any

from fastapi import APIRouter, Request

from app.schemas.portfolios import PortfolioResponse, PortfolioStatsResponse
from app.services.portfolio_service import PortfolioService

router = APIRouter()


@router.get("/portfolio/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(portfolio_id: str, request: Request, limit: int = 200) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    return service.get_portfolio(portfolio_id, limit)


@router.get("/portfolio/{portfolio_id}/stats", response_model=PortfolioStatsResponse)
def get_portfolio_stats(portfolio_id: str, request: Request) -> dict[str, Any]:
    service: PortfolioService = request.app.state.portfolio_service
    return service.get_stats(portfolio_id)
