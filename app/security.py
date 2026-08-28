from secrets import compare_digest

from app.domain.errors import AuthenticationError
from app.domain.identity import Principal


class ApiKeyAuthenticator:
    """Replaceable single-service principal boundary backed by configured API keys."""

    def __init__(self, principals_by_key: dict[str, Principal]) -> None:
        if not principals_by_key:
            raise ValueError("At least one API principal is required")
        self._principals_by_key = principals_by_key

    def authenticate(self, supplied_key: str | None) -> Principal:
        if not supplied_key:
            raise AuthenticationError
        for configured_key, principal in self._principals_by_key.items():
            if compare_digest(supplied_key, configured_key):
                return principal
        raise AuthenticationError
