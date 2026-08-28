class DomainError(Exception):
    pass


class AuthenticationError(DomainError):
    pass


class PortfolioAccessDeniedError(DomainError):
    pass


class InsufficientBankrollError(DomainError):
    pass


class BetAlreadySettledError(DomainError):
    pass


class InvalidLossPayoutError(DomainError):
    pass


class BetNotFoundError(DomainError):
    pass


class IdempotencyConflictError(DomainError):
    pass
