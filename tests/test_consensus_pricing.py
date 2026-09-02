from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import NotRequired, TypedDict, Unpack
from uuid import NAMESPACE_URL, UUID, uuid5

from app.domain.consensus import build_pricing_analysis
from app.domain.market_curve import (
    BookCurvePoint,
    load_market_curve_artifact,
    robust_market_center,
)
from app.domain.pricing import PricingObservation, PricingPolicy

EVENT_ID = uuid5(NAMESPACE_URL, "event:ncaaf-pricing")
START = datetime(2026, 8, 29, 23, 30, tzinfo=UTC)
AS_OF = datetime(2026, 8, 29, 20, 1, tzinfo=UTC)


class ObservationKwargs(TypedDict):
    observed_at: NotRequired[datetime]
    ingested_at: NotRequired[datetime | None]
    snapshot: NotRequired[str]
    league: NotRequired[str]
    event_id: NotRequired[UUID]
    event_review_status: NotRequired[str]
    match_review_status: NotRequired[str]
    observation_status: NotRequired[str]
    stale_after_seconds: NotRequired[int]
    snapshot_requested_at: NotRequired[datetime | None]


def identifier(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, value)


def observation(
    book: str,
    market: str,
    side: str,
    odds: int,
    *,
    point: str | None = None,
    observed_at: datetime = datetime(2026, 8, 29, 20, 0, tzinfo=UTC),
    ingested_at: datetime | None = None,
    snapshot: str = "initial",
    league: str = "NCAAF",
    event_id: UUID = EVENT_ID,
    event_review_status: str = "matched",
    match_review_status: str = "matched",
    observation_status: str = "active",
    stale_after_seconds: int = 7_200,
    snapshot_requested_at: datetime | None = None,
) -> PricingObservation:
    point_value = None if point is None else Decimal(point)
    sportsbook_id = identifier(f"book:{book}")
    observation_id = identifier(
        f"observation:{league}:{event_id}:{book}:{market}:{side}:{point}:{snapshot}"
    )
    names = {"home": "Coastal Tech", "away": "Mountain State", "over": "Over", "under": "Under"}
    return PricingObservation(
        observation_id=observation_id,
        snapshot_id=identifier(f"snapshot:{book}:{snapshot}"),
        event_id=event_id,
        league=league,
        home_team="Coastal Tech",
        away_team="Mountain State",
        scheduled_start_utc=START,
        event_review_status=event_review_status,
        sportsbook_id=sportsbook_id,
        sportsbook_key=book,
        sportsbook_name={"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM"}.get(
            book, book
        ),
        sportsbook_active=True,
        market_type=market,
        period="full_game",
        selection_side=side,
        selection_name=names[side],
        point=point_value,
        american_odds=odds,
        snapshot_requested_at=snapshot_requested_at or ingested_at or observed_at,
        observed_at=observed_at,
        ingested_at=ingested_at or observed_at,
        stale_after_seconds=stale_after_seconds,
        observation_status=observation_status,
        match_review_status=match_review_status,
    )


def pair(
    book: str,
    market: str,
    first_odds: int,
    second_odds: int,
    *,
    first_point: str | None = None,
    second_point: str | None = None,
    **kwargs: Unpack[ObservationKwargs],
) -> tuple[PricingObservation, PricingObservation]:
    sides = ("home", "away") if market in {"moneyline", "spread"} else ("over", "under")
    return (
        observation(book, market, sides[0], first_odds, point=first_point, **kwargs),
        observation(book, market, sides[1], second_odds, point=second_point, **kwargs),
    )


def policy(
    *,
    minimum_books: int = 2,
    minimum_ev: str = "-1",
    minimum_edge: str = "-1",
    outlier_threshold: str = "0.03",
    maximum_dispersion: str = "0.08",
) -> PricingPolicy:
    return PricingPolicy(
        minimum_books=minimum_books,
        minimum_ev=Decimal(minimum_ev),
        minimum_probability_edge=Decimal(minimum_edge),
        outlier_threshold=Decimal(outlier_threshold),
        maximum_dispersion=Decimal(maximum_dispersion),
        supported_books=frozenset({"draftkings", "fanduel", "betmgm"}),
    )


def test_market_grouping_uses_cross_line_spread_center_without_mixing_pair_sides() -> None:
    observations = (
        *pair("draftkings", "moneyline", -110, -110),
        *pair("fanduel", "moneyline", -110, -110),
        *pair("betmgm", "moneyline", -110, -110),
        *pair("draftkings", "spread", -110, -110, first_point="-3.5", second_point="3.5"),
        *pair("fanduel", "spread", -110, -110, first_point="-3.5", second_point="3.5"),
        *pair("betmgm", "spread", -110, -110, first_point="-4.0", second_point="4.0"),
        *pair("draftkings", "total", -110, -110, first_point="52.5", second_point="52.5"),
        *pair("fanduel", "total", -110, -110, first_point="52.5", second_point="52.5"),
        *pair("betmgm", "total", -110, -110, first_point="52.5", second_point="52.5"),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert len(result.opportunities) == 6
    spread = [item for item in result.opportunities if item.market_type == "spread"]
    assert {item.point for item in spread} == {Decimal("-3.5"), Decimal("4.0")}
    assert {item.books_contributing for item in spread} == {3}
    assert all(item.consensus_fair_point is not None for item in spread)
    assert all(item.line_advantage is not None for item in spread)
    assert "insufficient_books" not in result.rejection_counts


def test_inconsistent_points_and_missing_opposing_side_are_not_paired() -> None:
    observations = (
        observation("draftkings", "spread", "home", -110, point="-3.5"),
        observation("draftkings", "spread", "away", -110, point="4.0"),
        observation("betmgm", "total", "over", -110, point="51.5"),
        observation("betmgm", "total", "under", -110, point="52.5"),
        observation("fanduel", "total", "over", -110, point="52.5"),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert result.opportunities == ()
    assert result.rejection_counts["inconsistent_spread_points"] == 1
    assert result.rejection_counts["inconsistent_total_points"] == 1
    assert result.rejection_counts["incomplete_or_malformed_pair"] == 1


def test_stale_ambiguous_suspended_and_unsupported_observations_are_excluded() -> None:
    observations = (
        *pair("draftkings", "moneyline", -110, -110, stale_after_seconds=30),
        *pair("fanduel", "moneyline", -110, -110, event_review_status="conflict"),
        *pair("betmgm", "moneyline", -110, -110, observation_status="suspended"),
        *pair("caesars", "moneyline", -110, -110),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert result.opportunities == ()
    assert result.rejection_counts == {
        "ambiguous_event": 2,
        "inactive_observation": 2,
        "stale_snapshot": 2,
        "unsupported_or_inactive_book": 2,
    }


def test_fresh_snapshot_with_five_minute_old_provider_quote_remains_eligible() -> None:
    quote_time = datetime(2026, 8, 29, 19, 55, tzinfo=UTC)
    snapshot_time = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    observations = (
        *pair(
            "draftkings",
            "moneyline",
            -110,
            -110,
            observed_at=quote_time,
            ingested_at=snapshot_time,
            snapshot_requested_at=snapshot_time,
            stale_after_seconds=120,
        ),
        *pair(
            "fanduel",
            "moneyline",
            -110,
            -110,
            observed_at=quote_time,
            ingested_at=snapshot_time,
            snapshot_requested_at=snapshot_time,
            stale_after_seconds=120,
        ),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert result.funnel["eligible_observations"] == 4
    assert result.funnel["exact_paired_book_markets"] == 2
    assert result.funnel["calculable_candidate_sides"] == 2
    assert result.funnel["snapshot_age_seconds"] == 60
    assert result.funnel["provider_quote_age_median_seconds"] == 300
    assert "stale_snapshot" not in result.rejection_counts


def test_pathologically_old_provider_quotes_fail_closed_separately_from_snapshot_age() -> None:
    snapshot_time = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    old_quote = snapshot_time.replace(year=2025)
    observations = (
        *pair(
            "draftkings",
            "moneyline",
            -110,
            -110,
            observed_at=old_quote,
            ingested_at=snapshot_time,
            snapshot_requested_at=snapshot_time,
            stale_after_seconds=120,
        ),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert result.funnel["eligible_observations"] == 0
    assert result.rejection_counts == {"pathologically_old_provider_quote": 2}
    assert result.pipeline_status == "DEGRADED"


def test_freshest_snapshot_wins_even_when_its_provider_quote_timestamp_is_older() -> None:
    older_snapshot = datetime(2026, 8, 29, 19, 59, tzinfo=UTC)
    fresh_snapshot = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    observations = (
        *pair(
            "draftkings",
            "moneyline",
            120,
            -140,
            observed_at=older_snapshot,
            snapshot_requested_at=older_snapshot,
            snapshot="older",
        ),
        *pair(
            "draftkings",
            "moneyline",
            110,
            -130,
            observed_at=older_snapshot.replace(minute=55),
            snapshot_requested_at=fresh_snapshot,
            ingested_at=fresh_snapshot,
            snapshot="fresh",
        ),
        *pair(
            "fanduel",
            "moneyline",
            -110,
            -110,
            observed_at=older_snapshot.replace(minute=55),
            snapshot_requested_at=fresh_snapshot,
            ingested_at=fresh_snapshot,
            snapshot="fresh",
        ),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert result.funnel["latest_observations"] == 4
    assert {str(value) for item in result.candidates for value in item.snapshot_ids} == {
        str(identifier("snapshot:draftkings:fresh")),
        str(identifier("snapshot:fanduel:fresh")),
    }


def test_median_consensus_is_robust_reports_outlier_and_separates_best_price() -> None:
    observations = (
        *pair("draftkings", "moneyline", -110, -110),
        *pair("fanduel", "moneyline", -110, -110),
        *pair("betmgm", "moneyline", 110, -130),
    )

    result = build_pricing_analysis(
        observations,
        as_of=AS_OF,
        policy=policy(minimum_ev="0.01", minimum_edge="0.005"),
    )

    assert len(result.opportunities) == 1
    opportunity = result.opportunities[0]
    assert opportunity.selection_side == "home"
    assert opportunity.no_vig_consensus_probability == Decimal("0.5")
    assert opportunity.best_sportsbook_key == "betmgm"
    assert opportunity.best_american_odds == 110
    assert opportunity.raw_implied_probability == Decimal(10) / Decimal(21)
    assert opportunity.probability_edge == Decimal("0.5") - Decimal(10) / Decimal(21)
    assert opportunity.ev_per_unit == Decimal("0.05")
    assert opportunity.outlier_sportsbooks == ("betmgm",)
    assert opportunity.quality_warnings == (
        "material_book_outlier",
        "best_executable_book_outlier",
    )
    assert opportunity.proprietary_model_probability is None
    assert opportunity.final_fair_probability_source == "market_consensus"
    assert len(opportunity.source_observation_ids) == 6
    assert opportunity.best_executable_observation_id == identifier(
        "observation:NCAAF:"
        f"{EVENT_ID}:betmgm:moneyline:home:None:initial"
    )


def test_excessive_dispersion_rejects_market_instead_of_averaging_blindly() -> None:
    observations = (
        *pair("draftkings", "moneyline", -110, -110),
        *pair("fanduel", "moneyline", -110, -110),
        *pair("betmgm", "moneyline", 300, -500),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert result.opportunities == ()
    assert len(result.candidates) == 2
    assert all("excessive_consensus_dispersion" in item.pricing_gate_failures for item in result.candidates)
    assert result.rejection_counts["excessive_consensus_dispersion"] == 2


def test_integer_spread_and_total_do_not_assume_unknown_push_probability() -> None:
    observations = (
        *pair("draftkings", "spread", -110, -110, first_point="-4", second_point="4"),
        *pair("fanduel", "spread", -110, -110, first_point="-4", second_point="4"),
        *pair("draftkings", "total", -110, -110, first_point="52", second_point="52"),
        *pair("fanduel", "total", -110, -110, first_point="52", second_point="52"),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert len(result.candidates) == 4
    assert all(item.push_probability > 0 for item in result.candidates)
    assert all(
        item.final_fair_probability + item.push_probability + item.loss_probability
        == Decimal(1)
        for item in result.candidates
        if item.loss_probability is not None
    )
    assert "push_probability_not_modeled" not in result.rejection_counts


def test_zero_qualified_is_valid_and_top_n_is_a_per_league_ceiling() -> None:
    markets = (
        *pair("draftkings", "moneyline", -110, -110),
        *pair("fanduel", "moneyline", -110, -110),
        *pair("draftkings", "total", -110, -110, first_point="52.5", second_point="52.5"),
        *pair("fanduel", "total", -110, -110, first_point="52.5", second_point="52.5"),
    )
    zero = build_pricing_analysis(
        markets,
        as_of=AS_OF,
        policy=policy(minimum_ev="0.50", minimum_edge="0.50"),
    )
    limited = build_pricing_analysis(markets, as_of=AS_OF, policy=policy(), top_n_per_league=2)

    assert zero.opportunities == ()
    assert len(zero.candidates) == 4
    assert zero.opportunities_qualified == 0
    assert len(limited.opportunities) == 2
    assert limited.opportunities_qualified == 4
    assert limited.top_n_per_league == 2


def test_calculable_below_threshold_sides_survive_before_top_n_qualification() -> None:
    observations = (
        *pair("draftkings", "moneyline", 102, 102),
        *pair("fanduel", "moneyline", -110, -110),
    )

    result = build_pricing_analysis(
        observations,
        as_of=AS_OF,
        policy=policy(minimum_ev="0.015", minimum_edge="0.0075"),
        top_n_per_league=1,
    )

    assert result.opportunities == ()
    assert len(result.candidates) == 2
    assert all(item.final_fair_probability == Decimal("0.5") for item in result.candidates)
    assert all(item.best_american_odds == 102 for item in result.candidates)
    assert all(item.ev_per_unit == Decimal("0.010") for item in result.candidates)
    assert all(set(item.pricing_gate_failures) == {"below_minimum_edge", "below_minimum_ev"} for item in result.candidates)
    assert result.funnel["calculable_candidate_sides"] == 2
    assert result.funnel["positive_edge_candidates"] == 2
    assert result.funnel["positive_ev_candidates"] == 2


def test_cross_line_center_handles_fragmentation_and_integer_pushes() -> None:
    observations = (
        *pair("draftkings", "spread", -110, -110, first_point="-17", second_point="17"),
        *pair("fanduel", "spread", -110, -110, first_point="-17.5", second_point="17.5"),
        *pair("betmgm", "spread", -110, -110, first_point="-18", second_point="18"),
        *pair("draftkings", "total", -110, -110, first_point="51", second_point="51"),
        *pair("fanduel", "total", -110, -110, first_point="51.5", second_point="51.5"),
        *pair("betmgm", "total", -110, -110, first_point="52", second_point="52"),
    )

    result = build_pricing_analysis(observations, as_of=AS_OF, policy=policy())

    assert len(result.candidates) == 4
    assert result.funnel["exact_paired_book_markets"] == 6
    assert result.funnel["comparable_market_groups"] == 2
    assert all(item.books_contributing == 3 for item in result.candidates)
    assert "insufficient_books" not in result.rejection_counts
    assert "push_probability_not_modeled" not in result.rejection_counts

    whole_number = build_pricing_analysis(
        (
            *pair("draftkings", "spread", -110, -110, first_point="-17", second_point="17"),
            *pair("fanduel", "spread", -110, -110, first_point="-17", second_point="17"),
            *pair("draftkings", "total", -110, -110, first_point="51", second_point="51"),
            *pair("fanduel", "total", -110, -110, first_point="51", second_point="51"),
        ),
        as_of=AS_OF,
        policy=policy(),
    )
    assert whole_number.funnel["comparable_market_groups"] == 2
    assert whole_number.funnel["calculable_candidate_sides"] == 4
    assert all(item.push_probability > 0 for item in whole_number.candidates)
    assert "push_probability_not_modeled" not in whole_number.rejection_counts


def test_empirical_curve_is_monotonic_push_aware_and_hash_verified() -> None:
    artifact = load_market_curve_artifact()
    spread = artifact.curves["spread"]
    total = artifact.curves["total"]

    home_minus_four_and_half = spread.settlement(
        Decimal("4.5"), Decimal("-4.5"), "home"
    )
    home_minus_three_and_half = spread.settlement(
        Decimal("4.5"), Decimal("-3.5"), "home"
    )
    home_minus_three = spread.settlement(Decimal("4.5"), Decimal("-3"), "home")
    over_fifty_five_and_half = total.settlement(
        Decimal("55.5"), Decimal("55.5"), "over"
    )
    over_fifty_three_and_half = total.settlement(
        Decimal("55.5"), Decimal("53.5"), "over"
    )
    over_fifty_three = total.settlement(Decimal("55.5"), Decimal("53"), "over")

    assert home_minus_three_and_half.win > home_minus_four_and_half.win
    assert over_fifty_three_and_half.win > over_fifty_five_and_half.win
    assert home_minus_three.push > 0
    assert over_fifty_three.push > 0
    for settlement in (
        home_minus_four_and_half,
        home_minus_three_and_half,
        home_minus_three,
        over_fifty_five_and_half,
        over_fifty_three_and_half,
        over_fifty_three,
    ):
        assert settlement.win + settlement.push + settlement.loss == Decimal(1)
    assert artifact.artifact_hash == (
        "199e8170c86acb497b864b20b60abf190ce5a8cae1d6b8352e3ef584183c76bb"
    )


def test_robust_market_center_limits_one_obvious_outlier() -> None:
    result = robust_market_center(
        (
            BookCurvePoint("draftkings", Decimal("4.4"), Decimal("0.04")),
            BookCurvePoint("fanduel", Decimal("4.6"), Decimal("0.04")),
            BookCurvePoint("betmgm", Decimal("11.0"), Decimal("0.04")),
        ),
        outlier_distance=Decimal("3"),
    )

    assert Decimal("4.4") < result.center < Decimal("6")
    assert result.outlier_sportsbooks == ("betmgm",)


def test_cross_line_away_plus_six_and_half_and_under_fifty_eight_and_half_qualify() -> None:
    spread = build_pricing_analysis(
        (
            *pair("draftkings", "spread", -110, -110, first_point="-6.5", second_point="6.5"),
            *pair("fanduel", "spread", -110, -110, first_point="-4.5", second_point="4.5"),
            *pair("betmgm", "spread", -110, -110, first_point="-4.5", second_point="4.5"),
        ),
        as_of=AS_OF,
        policy=policy(minimum_ev="0.015", minimum_edge="0.0075"),
    )
    total = build_pricing_analysis(
        (
            *pair("draftkings", "total", -110, -110, first_point="58.5", second_point="58.5"),
            *pair("fanduel", "total", -110, -110, first_point="56.5", second_point="56.5"),
            *pair("betmgm", "total", -110, -110, first_point="56.5", second_point="56.5"),
        ),
        as_of=AS_OF,
        policy=policy(minimum_ev="0.015", minimum_edge="0.0075"),
    )

    away = next(item for item in spread.opportunities if item.selection_side == "away")
    under = next(item for item in total.opportunities if item.selection_side == "under")
    assert away.point == Decimal("6.5")
    assert away.line_advantage is not None and away.line_advantage > Decimal("1.5")
    assert away.ev_per_unit > Decimal("0.04")
    assert under.point == Decimal("58.5")
    assert under.line_advantage is not None and under.line_advantage > Decimal("1.5")
    assert under.ev_per_unit > Decimal("0.04")


def test_moderate_minus_175_and_plus_145_moneylines_can_qualify() -> None:
    favorite = build_pricing_analysis(
        (
            *pair("draftkings", "moneyline", -175, 160),
            *pair("fanduel", "moneyline", -220, 180),
            *pair("betmgm", "moneyline", -230, 190),
        ),
        as_of=AS_OF,
        policy=policy(minimum_ev="0.015", minimum_edge="0.0075"),
    )
    underdog = build_pricing_analysis(
        (
            *pair("draftkings", "moneyline", 145, -160),
            *pair("fanduel", "moneyline", 120, -150),
            *pair("betmgm", "moneyline", 115, -145),
        ),
        as_of=AS_OF,
        policy=policy(minimum_ev="0.015", minimum_edge="0.0075"),
    )

    favorite_home = next(item for item in favorite.opportunities if item.selection_side == "home")
    underdog_home = next(item for item in underdog.opportunities if item.selection_side == "home")
    assert favorite_home.best_american_odds == -175
    assert favorite_home.ev_per_unit >= Decimal("0.015")
    assert underdog_home.best_american_odds == 145
    assert underdog_home.ev_per_unit >= Decimal("0.015")


def test_replay_cutoff_uses_old_snapshot_before_move_and_latest_snapshot_after_move() -> None:
    ten = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    thirteen = datetime(2026, 8, 29, 13, 0, tzinfo=UTC)
    observations = (
        *pair(
            "draftkings",
            "spread",
            120,
            -140,
            first_point="-3.5",
            second_point="3.5",
            observed_at=ten,
            snapshot="10am",
            stale_after_seconds=20_000,
        ),
        *pair(
            "fanduel",
            "spread",
            -110,
            -110,
            first_point="-3.5",
            second_point="3.5",
            observed_at=ten,
            snapshot="10am",
            stale_after_seconds=20_000,
        ),
        *pair(
            "draftkings",
            "spread",
            120,
            -140,
            first_point="-4.5",
            second_point="4.5",
            observed_at=thirteen,
            snapshot="1pm",
            stale_after_seconds=20_000,
        ),
        *pair(
            "betmgm",
            "spread",
            -110,
            -110,
            first_point="-4.5",
            second_point="4.5",
            observed_at=thirteen,
            snapshot="1pm",
            stale_after_seconds=20_000,
        ),
    )

    at_eleven = build_pricing_analysis(
        observations,
        as_of=datetime(2026, 8, 29, 11, 0, tzinfo=UTC),
        policy=policy(),
    )
    at_fourteen = build_pricing_analysis(
        observations,
        as_of=datetime(2026, 8, 29, 14, 0, tzinfo=UTC),
        policy=policy(),
    )

    assert {item.point for item in at_eleven.opportunities} == {Decimal("-3.5"), Decimal("3.5")}
    assert all(identifier("snapshot:draftkings:1pm") not in item.snapshot_ids for item in at_eleven.opportunities)
    assert at_eleven.rejection_counts["after_cutoff"] == 4
    assert {item.point for item in at_fourteen.opportunities} == {Decimal("-4.5"), Decimal("4.5")}
    assert all(identifier("snapshot:draftkings:10am") not in item.snapshot_ids for item in at_fourteen.opportunities)


def test_replay_excludes_old_provider_observation_ingested_after_cutoff() -> None:
    ten = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    thirteen = datetime(2026, 8, 29, 13, 0, tzinfo=UTC)
    observations = (
        *pair(
            "draftkings",
            "moneyline",
            -110,
            -110,
            observed_at=ten,
            ingested_at=ten,
            snapshot="known-at-10",
            stale_after_seconds=20_000,
        ),
        *pair(
            "fanduel",
            "moneyline",
            -110,
            -110,
            observed_at=ten,
            ingested_at=ten,
            snapshot="known-at-10",
            stale_after_seconds=20_000,
        ),
        *pair(
            "betmgm",
            "moneyline",
            110,
            -130,
            observed_at=ten,
            ingested_at=thirteen,
            snapshot="late-ingestion",
            stale_after_seconds=20_000,
        ),
    )

    result = build_pricing_analysis(
        observations,
        as_of=datetime(2026, 8, 29, 11, 0, tzinfo=UTC),
        policy=policy(),
    )

    assert result.rejection_counts["after_cutoff"] == 2
    assert {item.books_contributing for item in result.opportunities} == {2}
    assert all(identifier("snapshot:betmgm:late-ingestion") not in item.snapshot_ids for item in result.opportunities)
