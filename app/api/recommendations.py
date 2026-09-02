from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.dependencies import require_principal
from app.domain.errors import (
    InsufficientBankrollError,
    PortfolioAccessDeniedError,
    RecommendationNotFoundError,
    RecommendationStateError,
)
from app.domain.identity import Principal
from app.schemas.bets import BetRecordedResponse
from app.schemas.recommendations import (
    RecommendationDecisionResponse,
    RecommendationListResponse,
    RecommendationRequest,
    RiskExposureResponse,
    WatchlistResponse,
)
from app.services.recommendation_service import RecommendationService

router = APIRouter()


def _service(request: Request) -> RecommendationService:
    service = getattr(request.app.state, "recommendation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Recommendation persistence is unavailable")
    return service


@router.post("/portfolio/{portfolio_id}/recommendations/analyze", response_model=RecommendationDecisionResponse)
def analyze_recommendations(
    portfolio_id: str,
    data: RecommendationRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
) -> dict[str, Any]:
    as_of = data.as_of or request.app.state.clock()
    try:
        return _service(request).analyze(
            principal,
            portfolio_id=portfolio_id,
            slate_date=data.slate_date,
            as_of=as_of,
            market_types=data.market_types,
            top_n=data.top_n,
            parlay_offers=(),
        )
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/portfolio/{portfolio_id}/recommendations", response_model=RecommendationListResponse)
def list_recommendations(
    portfolio_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    slate_date: date | None = None,
    upcoming_only: bool = False,
) -> dict[str, Any]:
    try:
        if upcoming_only and slate_date is not None:
            raise HTTPException(status_code=422, detail="slate_date and upcoming_only cannot be combined")
        service = _service(request)
        return {
            "recommendations": service.list(
                principal,
                portfolio_id,
                slate_date=slate_date,
                upcoming_as_of=request.app.state.clock() if upcoming_only else None,
            ),
            "latest_decision": service.latest_decision(principal, portfolio_id, slate_date=slate_date),
        }
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None


@router.post("/recommendations/{recommendation_id}/approve", response_model=BetRecordedResponse)
def approve_recommendation(
    recommendation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> dict[str, Any]:
    try:
        return _service(request).approve(principal, recommendation_id, idempotency_key=idempotency_key)
    except RecommendationNotFoundError:
        raise HTTPException(status_code=404, detail="Recommendation not found") from None
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None
    except RecommendationStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except InsufficientBankrollError:
        raise HTTPException(status_code=400, detail="Insufficient bankroll for the recommended stake") from None


@router.get("/portfolio/{portfolio_id}/watchlist", response_model=WatchlistResponse)
def portfolio_watchlist(
    portfolio_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    upcoming_only: bool = True,
) -> dict[str, Any]:
    if not upcoming_only:
        raise HTTPException(status_code=422, detail="Only current upcoming watchlist state is supported")
    try:
        return _service(request).watchlist(principal, portfolio_id, as_of=request.app.state.clock())
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None


@router.post("/recommendations/{recommendation_id}/reject")
def reject_recommendation(
    recommendation_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
) -> dict[str, Any]:
    try:
        return {"recommendation": _service(request).reject(principal, recommendation_id)}
    except RecommendationNotFoundError:
        raise HTTPException(status_code=404, detail="Recommendation not found") from None
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None
    except RecommendationStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/portfolio/{portfolio_id}/risk", response_model=RiskExposureResponse)
def portfolio_risk(
    portfolio_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    slate_date: date,
) -> dict[str, Any]:
    try:
        return _service(request).risk(principal, portfolio_id, slate_date)
    except PortfolioAccessDeniedError:
        raise HTTPException(status_code=403, detail="Portfolio belongs to another owner") from None
