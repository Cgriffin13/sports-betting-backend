def validate_american_odds(value: int) -> int:
    """Accept standard American prices: +100 or greater, or -100 or less."""
    if -100 < value < 100:
        raise ValueError("American odds must be <= -100 or >= 100")
    return value
