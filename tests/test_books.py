from app.domain.books import normalize_book


def test_current_supported_us_book_keys_are_stable() -> None:
    expected = {
        "betmgm": "BetMGM",
        "betrivers": "BetRivers",
        "williamhill_us": "Caesars",
        "draftkings": "DraftKings",
        "fanatics": "Fanatics",
        "fanduel": "FanDuel",
    }

    assert {key: normalize_book(key, None)[1] for key in expected} == expected


def test_provider_key_is_authoritative_and_titles_normalize_when_key_is_absent() -> None:
    assert normalize_book("williamhill_us", "Caesars Sportsbook") == ("williamhill_us", "Caesars")
    assert normalize_book(None, "CAESARS SPORTSBOOK") == ("williamhill_us", "Caesars")
    assert normalize_book(None, "Fanatics Sportsbook") == ("fanatics", "Fanatics")
    assert normalize_book(None, "Draft Kings") == ("draftkings", "DraftKings")


def test_unapproved_book_remains_normalized_but_not_silently_allowlisted() -> None:
    assert normalize_book("bovada", "Bovada") == ("bovada", "Bovada")
