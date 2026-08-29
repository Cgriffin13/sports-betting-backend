from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import require_principal
from app.domain.identity import Principal
from app.schemas.opportunities import OpportunitiesRequest, PricingAnalysisResponse
from app.services.pricing_service import PricingService

router = APIRouter()


@router.post("/opportunities", response_model=PricingAnalysisResponse)
def analyze_opportunities(
    data: OpportunitiesRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
) -> PricingAnalysisResponse:
    del principal
    service: PricingService = request.app.state.pricing_service
    as_of = data.as_of or request.app.state.clock()
    try:
        analysis = service.analyze(
            leagues=data.leagues,
            market_types=data.market_types,
            as_of=as_of,
            event_date=data.event_date,
            top_n=data.top_n,
            pricing_policy_version=data.pricing_policy_version,
            qualification_policy_version=data.qualification_policy_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return PricingAnalysisResponse.from_domain(analysis)
