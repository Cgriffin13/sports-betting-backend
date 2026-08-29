from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeAlias
from uuid import UUID

from app.domain.pricing import (
    FAIR_PROBABILITY_SOURCE,
    BookNoVigPrice,
    PricingAnalysis,
    PricingObservation,
    PricingOpportunity,
    PricingPolicy,
    american_odds_to_decimal,
    american_odds_to_implied_probability,
    expected_value_binary,
    probability_edge,
    remove_vig_proportionally,
    unweighted_median_consensus,
)

FamilyKey: TypeAlias = tuple[UUID, UUID, str, str]
LineKey: TypeAlias = tuple[UUID, str, str, str]


@dataclass(frozen=True, slots=True)
class _PairedBookMarket:
    event_id: UUID
    league: str
    home_team: str
    away_team: str
    scheduled_start_utc: datetime
    sportsbook_key: str
    sportsbook_name: str
    market_type: str
    period: str
    line_key: str
    observations: dict[str, PricingObservation]
    probabilities: dict[str, Decimal]
    raw_probability_sum: Decimal
    overround: Decimal


def build_pricing_analysis(
    observations: tuple[PricingObservation, ...],
    *,
    as_of: datetime,
    policy: PricingPolicy,
    top_n_per_league: int = 10,
) -> PricingAnalysis:
    if top_n_per_league < 1:
        raise ValueError("Top N must be positive")
    cutoff = _as_utc(as_of)
    rejections: Counter[str] = Counter()
    time_bound = [item for item in observations if _is_known_by(item, cutoff, rejections)]
    latest = _latest_market_states(time_bound)
    eligible = [item for item in latest if _is_eligible(item, cutoff, policy, rejections)]
    paired = _pair_book_markets(eligible, rejections)
    qualified = _build_opportunities(paired, cutoff, policy, rejections)
    opportunities = _top_n_by_league(qualified, top_n_per_league)
    return PricingAnalysis(
        as_of=cutoff,
        pricing_policy_version=policy.pricing_version,
        qualification_policy_version=policy.qualification_version,
        opportunities=tuple(opportunities),
        observations_considered=len(observations),
        paired_book_markets=len(paired),
        opportunities_qualified=len(qualified),
        top_n_per_league=top_n_per_league,
        rejection_counts=dict(sorted(rejections.items())),
    )


def _is_known_by(item: PricingObservation, cutoff: datetime, rejections: Counter[str]) -> bool:
    if _as_utc(item.observed_at) > cutoff or _as_utc(item.ingested_at) > cutoff:
        rejections["after_cutoff"] += 1
        return False
    return True


def _latest_market_states(observations: list[PricingObservation]) -> list[PricingObservation]:
    families: dict[FamilyKey, list[PricingObservation]] = defaultdict(list)
    for item in observations:
        families[(item.event_id, item.sportsbook_id, item.market_type, item.period)].append(item)

    selected: list[PricingObservation] = []
    for items in families.values():
        latest = max(
            items,
            key=lambda item: (
                _as_utc(item.observed_at),
                _as_utc(item.snapshot_requested_at),
                _as_utc(item.ingested_at),
                str(item.snapshot_id),
            ),
        )
        selected.extend(item for item in items if item.snapshot_id == latest.snapshot_id)
    return selected


def _is_eligible(
    item: PricingObservation,
    cutoff: datetime,
    policy: PricingPolicy,
    rejections: Counter[str],
) -> bool:
    if item.sportsbook_key not in policy.supported_books or not item.sportsbook_active:
        rejections["unsupported_or_inactive_book"] += 1
        return False
    if item.event_review_status != "matched" or item.match_review_status != "matched":
        rejections["ambiguous_event"] += 1
        return False
    if item.observation_status != "active":
        rejections["inactive_observation"] += 1
        return False
    if _as_utc(item.scheduled_start_utc) <= cutoff:
        rejections["event_started"] += 1
        return False
    age_seconds = int((cutoff - _as_utc(item.observed_at)).total_seconds())
    if age_seconds > item.stale_after_seconds:
        rejections["stale_observation"] += 1
        return False
    return True


def _pair_book_markets(
    observations: list[PricingObservation],
    rejections: Counter[str],
) -> list[_PairedBookMarket]:
    grouped: dict[tuple[UUID, UUID, str, str, str], list[PricingObservation]] = defaultdict(list)
    for item in observations:
        try:
            line_key = _canonical_line_key(item)
        except ValueError:
            rejections["malformed_market"] += 1
            continue
        grouped[(item.event_id, item.sportsbook_id, item.market_type, item.period, line_key)].append(item)

    pairs: list[_PairedBookMarket] = []
    for items in grouped.values():
        by_side = {item.selection_side: item for item in items}
        expected = _expected_sides(items[0].market_type)
        if set(by_side) != set(expected) or len(items) != 2:
            rejections["incomplete_or_malformed_pair"] += 1
            continue
        first, second = (by_side[expected[0]], by_side[expected[1]])
        if items[0].market_type == "spread" and first.point != -second.point:  # type: ignore[operator]
            rejections["inconsistent_spread_points"] += 1
            continue
        if items[0].market_type == "total" and first.point != second.point:
            rejections["inconsistent_total_points"] += 1
            continue
        raw = (
            american_odds_to_implied_probability(first.american_odds),
            american_odds_to_implied_probability(second.american_odds),
        )
        normalized = remove_vig_proportionally(raw)
        pairs.append(
            _PairedBookMarket(
                event_id=first.event_id,
                league=first.league,
                home_team=first.home_team,
                away_team=first.away_team,
                scheduled_start_utc=first.scheduled_start_utc,
                sportsbook_key=first.sportsbook_key,
                sportsbook_name=first.sportsbook_name,
                market_type=first.market_type,
                period=first.period,
                line_key=_canonical_line_key(first),
                observations=by_side,
                probabilities={expected[0]: normalized.probabilities[0], expected[1]: normalized.probabilities[1]},
                raw_probability_sum=normalized.raw_probability_sum,
                overround=normalized.overround,
            )
        )
    return pairs


def _build_opportunities(
    pairs: list[_PairedBookMarket],
    calculated_at: datetime,
    policy: PricingPolicy,
    rejections: Counter[str],
) -> list[PricingOpportunity]:
    markets: dict[LineKey, list[_PairedBookMarket]] = defaultdict(list)
    for pair in pairs:
        markets[(pair.event_id, pair.market_type, pair.period, pair.line_key)].append(pair)

    opportunities: list[PricingOpportunity] = []
    for book_markets in markets.values():
        book_markets.sort(key=lambda item: item.sportsbook_key)
        if len(book_markets) < policy.minimum_books:
            rejections["insufficient_books"] += 1
            continue
        market_type = book_markets[0].market_type
        for side in _expected_sides(market_type):
            probabilities = tuple(item.probabilities[side] for item in book_markets)
            consensus_result = unweighted_median_consensus(
                probabilities,
                outlier_threshold=policy.outlier_threshold,
            )
            consensus = consensus_result.probability
            dispersion = consensus_result.dispersion
            outliers = tuple(sorted(book_markets[index].sportsbook_key for index in consensus_result.outlier_indexes))
            if dispersion > policy.maximum_dispersion:
                rejections["excessive_consensus_dispersion"] += 1
                continue
            selections = [item.observations[side] for item in book_markets]
            best = max(selections, key=lambda item: (american_odds_to_decimal(item.american_odds), item.sportsbook_key))
            if market_type in {"spread", "total"} and not _is_half_point(best.point):
                rejections["push_probability_not_modeled"] += 1
                continue
            implied = american_odds_to_implied_probability(best.american_odds)
            decimal_odds = american_odds_to_decimal(best.american_odds)
            edge = probability_edge(consensus, implied)
            ev = expected_value_binary(consensus, decimal_odds)
            if edge < policy.minimum_probability_edge:
                rejections["below_minimum_edge"] += 1
                continue
            if ev < policy.minimum_ev:
                rejections["below_minimum_ev"] += 1
                continue
            source_ids = tuple(
                sorted(
                    {
                        observation.observation_id
                        for item in book_markets
                        for observation in item.observations.values()
                    },
                    key=str,
                )
            )
            snapshot_ids = tuple(
                sorted(
                    {
                        observation.snapshot_id
                        for item in book_markets
                        for observation in item.observations.values()
                    },
                    key=str,
                )
            )
            warnings = tuple(["material_book_outlier"] if outliers else [])
            first = book_markets[0]
            opportunity = PricingOpportunity(
                event_id=first.event_id,
                league=first.league,
                home_team=first.home_team,
                away_team=first.away_team,
                scheduled_start_utc=first.scheduled_start_utc,
                market_type=market_type,
                period=first.period,
                selection_side=side,
                selection_name=best.selection_name,
                point=best.point,
                best_sportsbook_key=best.sportsbook_key,
                best_sportsbook_name=best.sportsbook_name,
                best_american_odds=best.american_odds,
                best_decimal_odds=decimal_odds,
                raw_implied_probability=implied,
                no_vig_consensus_probability=consensus,
                proprietary_model_probability=None,
                final_fair_probability_source=FAIR_PROBABILITY_SOURCE,
                final_fair_probability=consensus,
                probability_edge=edge,
                ev_per_unit=ev,
                books_contributing=len(book_markets),
                consensus_dispersion=dispersion,
                uncertainty_indicator=_uncertainty_indicator(dispersion, policy),
                outlier_sportsbooks=outliers,
                quality_warnings=warnings,
                vig_removal_policy_version=policy.vig_removal_version,
                consensus_policy_version=policy.consensus_version,
                pricing_policy_version=policy.pricing_version,
                qualification_policy_version=policy.qualification_version,
                source_observation_ids=source_ids,
                best_executable_observation_id=best.observation_id,
                snapshot_ids=snapshot_ids,
                book_probabilities=tuple(_book_price(item, side) for item in book_markets),
                calculated_at=calculated_at,
            )
            opportunities.append(opportunity)
    opportunities.sort(key=_opportunity_sort_key)
    return opportunities


def _book_price(item: _PairedBookMarket, side: str) -> BookNoVigPrice:
    opposing = _opposing_side(item.market_type, side)
    selected_observation = item.observations[side]
    opposing_observation = item.observations[opposing]
    return BookNoVigPrice(
        sportsbook_key=item.sportsbook_key,
        sportsbook_name=item.sportsbook_name,
        selection_probability=item.probabilities[side],
        opposing_probability=item.probabilities[opposing],
        raw_probability_sum=item.raw_probability_sum,
        overround=item.overround,
        selection_observation_id=selected_observation.observation_id,
        opposing_observation_id=opposing_observation.observation_id,
        snapshot_ids=tuple(sorted({selected_observation.snapshot_id, opposing_observation.snapshot_id}, key=str)),
    )


def _canonical_line_key(item: PricingObservation) -> str:
    if item.market_type == "moneyline":
        if item.point is not None:
            raise ValueError("Moneyline cannot have a point")
        return "none"
    if item.point is None:
        raise ValueError("Spread and total require a point")
    point = -item.point if item.market_type == "spread" and item.selection_side == "away" else item.point
    return format(point, ".3f")


def _expected_sides(market_type: str) -> tuple[str, str]:
    if market_type in {"moneyline", "spread"}:
        return "home", "away"
    if market_type == "total":
        return "over", "under"
    raise ValueError(f"Unsupported market type '{market_type}'")


def _opposing_side(market_type: str, side: str) -> str:
    first, second = _expected_sides(market_type)
    return second if side == first else first


def _is_half_point(point: Decimal | None) -> bool:
    if point is None:
        return False
    return abs(point * 2) % 2 == 1


def _uncertainty_indicator(dispersion: Decimal, policy: PricingPolicy) -> str:
    if dispersion <= policy.outlier_threshold / Decimal(2):
        return "low"
    if dispersion <= policy.outlier_threshold:
        return "moderate"
    return "high"


def _opportunity_sort_key(item: PricingOpportunity) -> tuple[object, ...]:
    return (
        -item.ev_per_unit,
        -item.books_contributing,
        item.consensus_dispersion,
        item.scheduled_start_utc,
        str(item.event_id),
        item.market_type,
        item.selection_side,
        item.point or Decimal(0),
    )


def _top_n_by_league(opportunities: list[PricingOpportunity], top_n: int) -> list[PricingOpportunity]:
    counts: Counter[str] = Counter()
    selected: list[PricingOpportunity] = []
    for opportunity in opportunities:
        if counts[opportunity.league] >= top_n:
            continue
        selected.append(opportunity)
        counts[opportunity.league] += 1
    return selected


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Pricing timestamps must be timezone-aware")
    return value.astimezone(UTC)
