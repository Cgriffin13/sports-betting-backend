from typing import Annotated

from fastapi import Header, HTTPException, Request

from app.domain.errors import AuthenticationError
from app.domain.identity import Principal
from app.security import ApiKeyAuthenticator


def require_principal(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    authenticator: ApiKeyAuthenticator = request.app.state.authenticator
    try:
        return authenticator.authenticate(x_api_key)
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid or missing API key") from None
