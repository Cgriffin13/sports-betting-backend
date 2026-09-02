from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
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
    expected_value_with_push,
    probability_edge,
    remove_vig_proportionally,
    unweighted_median_consensus,
)
from app.domain.market_curve import (
    MARKET_CURVE_POLICY_VERSION,
    BookCurvePoint,
    EmpiricalMarketCurve,
    SettlementProbability,
    load_market_curve_artifact,
    probability_edge_with_push,
    robust_market_center,
)

FamilyKey: TypeAlias = tuple[UUID, UUID, str, str]
MarketKey: TypeAlias = tuple[UUID, str, str]


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
    candidates, qualified, comparable_groups = _build_opportunities(
        paired,
        cutoff,
        policy,
        rejections,
    )
    opportunities = _top_n_by_league(qualified, top_n_per_league)
    games_received = len({item.event_id for item in observations})
    games_analyzed = len({item.event_id for item in latest})
    quote_ages = sorted(_provider_quote_age_seconds(item) for item in latest)
    snapshot_ages = sorted(max(0, int((cutoff - _as_utc(item.snapshot_requested_at)).total_seconds())) for item in latest)
    supported = [item for item in latest if item.sportsbook_key in policy.supported_books and item.sportsbook_active]
    unsupported = [
        item for item in latest if item.sportsbook_key not in policy.supported_books or not item.sportsbook_active
    ]
    funnel = {
        "games_received": games_received,
        "games_analyzed": games_analyzed,
        "observations_received": len(observations),
        "observations_considered": len(time_bound),
        "latest_observations": len(latest),
        "supported_book_observations": len(supported),
        "unsupported_book_observations": len(unsupported),
        "supported_books_seen": len({item.sportsbook_key for item in supported}),
        "unsupported_books_seen": len({item.sportsbook_key for item in unsupported}),
        "snapshot_age_seconds": max(snapshot_ages, default=0),
        "provider_quote_age_min_seconds": min(quote_ages, default=0),
        "provider_quote_age_median_seconds": _percentile(quote_ages, 0.5),
        "provider_quote_age_p90_seconds": _percentile(quote_ages, 0.9),
        "provider_quote_age_max_seconds": max(quote_ages, default=0),
        "eligible_observations": len(eligible),
        "exact_paired_book_markets": len(paired),
        "comparable_market_groups": comparable_groups,
        "calculable_candidate_sides": len(candidates),
        "positive_edge_candidates": sum(item.probability_edge > 0 for item in candidates),
        "positive_ev_candidates": sum(item.ev_per_unit > 0 for item in candidates),
        "pricing_qualified_candidates": len(qualified),
    }
    pipeline_status, pipeline_reason = _pipeline_integrity(funnel)
    return PricingAnalysis(
        as_of=cutoff,
        pricing_policy_version=policy.pricing_version,
        qualification_policy_version=policy.qualification_version,
        first_scheduled_start_utc=min(
            (_as_utc(item.scheduled_start_utc) for item in latest if _as_utc(item.scheduled_start_utc) > cutoff),
            default=None,
        ),
        candidates=tuple(candidates),
        opportunities=tuple(opportunities),
        events_analyzed=games_analyzed,
        observations_considered=len(observations),
        paired_book_markets=len(paired),
        opportunities_qualified=len(qualified),
        top_n_per_league=top_n_per_league,
        rejection_counts=dict(sorted(rejections.items())),
        funnel=funnel,
        pipeline_status=pipeline_status,
        pipeline_status_reason=pipeline_reason,
    )


def _is_known_by(item: PricingObservation, cutoff: datetime, rejections: Counter[str]) -> bool:
    if (
        _as_utc(item.observed_at) > cutoff
        or _as_utc(item.snapshot_requested_at) > cutoff
        or _as_utc(item.ingested_at) > cutoff
    ):
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
                _as_utc(item.snapshot_requested_at),
                _as_utc(item.observed_at),
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
    snapshot_age_seconds = max(0, int((cutoff - _as_utc(item.snapshot_requested_at)).total_seconds()))
    if snapshot_age_seconds > item.stale_after_seconds:
        rejections["stale_snapshot"] += 1
        return False
    if _provider_quote_age_seconds(item) > policy.maximum_provider_quote_age_seconds:
        rejections["pathologically_old_provider_quote"] += 1
        return False
    return True


def _provider_quote_age_seconds(item: PricingObservation) -> int:
    return max(0, int((_as_utc(item.snapshot_requested_at) - _as_utc(item.observed_at)).total_seconds()))


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    return values[max(0, ceil(len(values) * fraction) - 1)]


def _pipeline_integrity(funnel: dict[str, int]) -> tuple[str, str | None]:
    if funnel["games_received"] > 0 and funnel["observations_received"] > 0 and funnel["eligible_observations"] == 0:
        return "DEGRADED", "observations_present_but_none_eligible"
    if (
        funnel["games_analyzed"] >= 10
        and funnel["latest_observations"] >= 20
        and funnel["exact_paired_book_markets"] == 0
    ):
        return "DEGRADED", "material_slate_has_no_exact_book_pairs"
    return "HEALTHY", None


def _pair_book_markets(
    observations: list[PricingObservation],
    rejections: Counter[str],
) -> list[_PairedBookMarket]:
    grouped: dict[tuple[UUID, UUID, str, str], list[PricingObservation]] = defaultdict(list)
    for item in observations:
        grouped[(item.event_id, item.sportsbook_id, item.market_type, item.period)].append(item)

    pairs: list[_PairedBookMarket] = []
    for family_items in grouped.values():
        market_type = family_items[0].market_type
        expected = _expected_sides(market_type)
        by_side_all: dict[str, list[PricingObservation]] = defaultdict(list)
        malformed = False
        for item in family_items:
            if item.selection_side not in expected:
                malformed = True
                continue
            try:
                _canonical_line_key(item)
            except ValueError:
                malformed = True
                continue
            by_side_all[item.selection_side].append(item)
        if malformed:
            rejections["malformed_market"] += 1
        if len(family_items) == 2 and all(len(by_side_all[side]) == 1 for side in expected):
            first, second = by_side_all[expected[0]][0], by_side_all[expected[1]][0]
            if market_type == "spread" and first.point != -second.point:  # type: ignore[operator]
                rejections["inconsistent_spread_points"] += 1
                continue
            if market_type == "total" and first.point != second.point:
                rejections["inconsistent_total_points"] += 1
                continue
            line_groups = [[first, second]]
        else:
            grouped_by_line: dict[str, list[PricingObservation]] = defaultdict(list)
            for item in family_items:
                try:
                    grouped_by_line[_canonical_line_key(item)].append(item)
                except ValueError:
                    continue
            line_groups = list(grouped_by_line.values())
        for items in line_groups:
            by_side = {item.selection_side: item for item in items}
            if set(by_side) != set(expected) or len(items) != 2:
                rejections["incomplete_or_malformed_pair"] += 1
                continue
            first, second = (by_side[expected[0]], by_side[expected[1]])
            if market_type == "spread" and first.point != -second.point:  # type: ignore[operator]
                rejections["inconsistent_spread_points"] += 1
                continue
            if market_type == "total" and first.point != second.point:
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
                    market_type=market_type,
                    period=first.period,
                    line_key=_canonical_line_key(first),
                    observations=by_side,
                    probabilities={
                        expected[0]: normalized.probabilities[0],
                        expected[1]: normalized.probabilities[1],
                    },
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
) -> tuple[list[PricingOpportunity], list[PricingOpportunity], int]:
    markets: dict[MarketKey, list[_PairedBookMarket]] = defaultdict(list)
    for pair in pairs:
        markets[(pair.event_id, pair.market_type, pair.period)].append(pair)

    candidates: list[PricingOpportunity] = []
    qualified: list[PricingOpportunity] = []
    for book_markets in markets.values():
        book_markets = _one_main_pair_per_book(book_markets)
        if len(book_markets) < policy.minimum_books:
            rejections["insufficient_books"] += 1
            continue
        market_type = book_markets[0].market_type
        if market_type == "moneyline":
            market_candidates = _moneyline_opportunities(
                book_markets,
                calculated_at,
                policy,
                rejections,
            )
        else:
            market_candidates = _cross_line_opportunities(
                book_markets,
                calculated_at,
                policy,
                rejections,
            )
        candidates.extend(market_candidates)
        qualified.extend(item for item in market_candidates if not item.pricing_gate_failures)
    candidates.sort(key=_opportunity_sort_key)
    qualified.sort(key=_opportunity_sort_key)
    return candidates, qualified, len(markets)


def _moneyline_opportunities(
    book_markets: list[_PairedBookMarket],
    calculated_at: datetime,
    policy: PricingPolicy,
    rejections: Counter[str],
) -> list[PricingOpportunity]:
    opportunities: list[PricingOpportunity] = []
    for side in _expected_sides("moneyline"):
        probabilities = tuple(item.probabilities[side] for item in book_markets)
        consensus_result = unweighted_median_consensus(
            probabilities,
            outlier_threshold=policy.outlier_threshold,
        )
        selections = [item.observations[side] for item in book_markets]
        best = max(
            selections,
            key=lambda item: (american_odds_to_decimal(item.american_odds), item.sportsbook_key),
        )
        consensus = consensus_result.probability
        implied = american_odds_to_implied_probability(best.american_odds)
        decimal_odds = american_odds_to_decimal(best.american_odds)
        edge = probability_edge(consensus, implied)
        ev = expected_value_binary(consensus, decimal_odds)
        outliers = tuple(
            sorted(book_markets[index].sportsbook_key for index in consensus_result.outlier_indexes)
        )
        opportunities.append(
            _opportunity(
                book_markets=book_markets,
                side=side,
                best=best,
                fair_probability=consensus,
                push_probability=Decimal(0),
                loss_probability=Decimal(1) - consensus,
                implied_probability=implied,
                decimal_odds=decimal_odds,
                edge=edge,
                ev=ev,
                dispersion=consensus_result.dispersion,
                outliers=outliers,
                calculated_at=calculated_at,
                policy=policy,
                rejections=rejections,
                book_probabilities=tuple(_book_price(item, side) for item in book_markets),
                consensus_fair_point=None,
                line_advantage=None,
                center_dispersion=None,
                market_probability_policy_version="exact-line-moneyline-v1",
                market_curve_artifact_hash=None,
            )
        )
    return opportunities


def _cross_line_opportunities(
    book_markets: list[_PairedBookMarket],
    calculated_at: datetime,
    policy: PricingPolicy,
    rejections: Counter[str],
) -> list[PricingOpportunity]:
    market_type = book_markets[0].market_type
    curve_key = "spread" if market_type == "spread" else "total"
    artifact = load_market_curve_artifact()
    curve = artifact.curves[curve_key]
    first_side = _expected_sides(market_type)[0]
    curve_points = tuple(
        BookCurvePoint(
            sportsbook_key=item.sportsbook_key,
            center=curve.infer_center(
                item.observations[first_side].point,  # type: ignore[arg-type]
                item.probabilities[first_side],
            ),
            overround=item.overround,
        )
        for item in book_markets
    )
    robust = robust_market_center(curve_points, outlier_distance=Decimal("3"))
    center_by_book = {item.sportsbook_key: item.center for item in curve_points}
    opportunities: list[PricingOpportunity] = []
    for side in _expected_sides(market_type):
        priced: list[
            tuple[Decimal, Decimal, Decimal, PricingObservation, SettlementProbability]
        ] = []
        for item in book_markets:
            observation = item.observations[side]
            if observation.point is None:
                continue
            settlement = curve.settlement(robust.center, observation.point, side)  # type: ignore[arg-type]
            decimal_odds = american_odds_to_decimal(observation.american_odds)
            implied = american_odds_to_implied_probability(observation.american_odds)
            edge = probability_edge_with_push(settlement.win, settlement.push, implied)
            ev = expected_value_with_push(settlement.win, settlement.loss, decimal_odds)
            priced.append((ev, edge, decimal_odds, observation, settlement))
        if not priced:
            continue
        ev, edge, decimal_odds, best, settlement = max(
            priced,
            key=lambda item: (item[0], item[1], item[2], item[3].sportsbook_key),
        )
        assert best.point is not None
        projected = tuple(
            _projected_book_price(
                item,
                side,
                best.point,
                curve,
                center_by_book[item.sportsbook_key],
            )
            for item in book_markets
        )
        conditional_probabilities = tuple(
            value.selection_probability
            / (value.selection_probability + value.opposing_probability)
            for value in projected
        )
        dispersion = max(conditional_probabilities) - min(conditional_probabilities)
        consensus_conditional = settlement.conditional_win
        outliers = tuple(
            sorted(
                value.sportsbook_key
                for value, probability in zip(projected, conditional_probabilities, strict=True)
                if abs(probability - consensus_conditional) > policy.outlier_threshold
            )
        )
        opportunities.append(
            _opportunity(
                book_markets=book_markets,
                side=side,
                best=best,
                fair_probability=settlement.win,
                push_probability=settlement.push,
                loss_probability=settlement.loss,
                implied_probability=american_odds_to_implied_probability(best.american_odds),
                decimal_odds=decimal_odds,
                edge=edge,
                ev=ev,
                dispersion=dispersion,
                outliers=outliers,
                calculated_at=calculated_at,
                policy=policy,
                rejections=rejections,
                book_probabilities=projected,
                consensus_fair_point=-robust.center if market_type == "spread" else robust.center,
                line_advantage=_line_advantage(market_type, side, robust.center, best.point),
                center_dispersion=robust.center_dispersion,
                market_probability_policy_version=MARKET_CURVE_POLICY_VERSION,
                market_curve_artifact_hash=artifact.artifact_hash,
            )
        )
    return opportunities


def _opportunity(
    *,
    book_markets: list[_PairedBookMarket],
    side: str,
    best: PricingObservation,
    fair_probability: Decimal,
    push_probability: Decimal,
    loss_probability: Decimal,
    implied_probability: Decimal,
    decimal_odds: Decimal,
    edge: Decimal,
    ev: Decimal,
    dispersion: Decimal,
    outliers: tuple[str, ...],
    calculated_at: datetime,
    policy: PricingPolicy,
    rejections: Counter[str],
    book_probabilities: tuple[BookNoVigPrice, ...],
    consensus_fair_point: Decimal | None,
    line_advantage: Decimal | None,
    center_dispersion: Decimal | None,
    market_probability_policy_version: str,
    market_curve_artifact_hash: str | None,
) -> PricingOpportunity:
    failures: list[str] = []
    if dispersion > policy.maximum_dispersion:
        rejections["excessive_consensus_dispersion"] += 1
        failures.append("excessive_consensus_dispersion")
    if edge < policy.minimum_probability_edge:
        rejections["below_minimum_edge"] += 1
        failures.append("below_minimum_edge")
    if ev < policy.minimum_ev:
        rejections["below_minimum_ev"] += 1
        failures.append("below_minimum_ev")
    source_ids, snapshot_ids = _source_ids(book_markets)
    warnings: tuple[str, ...] = ()
    if outliers:
        warnings = ("material_book_outlier",)
        if best.sportsbook_key in outliers:
            warnings += ("best_executable_book_outlier",)
    first = book_markets[0]
    return PricingOpportunity(
        event_id=first.event_id,
        league=first.league,
        home_team=first.home_team,
        away_team=first.away_team,
        scheduled_start_utc=first.scheduled_start_utc,
        market_type=first.market_type,
        period=first.period,
        selection_side=side,
        selection_name=best.selection_name,
        point=best.point,
        best_sportsbook_key=best.sportsbook_key,
        best_sportsbook_name=best.sportsbook_name,
        best_american_odds=best.american_odds,
        best_decimal_odds=decimal_odds,
        raw_implied_probability=implied_probability,
        no_vig_consensus_probability=fair_probability,
        proprietary_model_probability=None,
        final_fair_probability_source=FAIR_PROBABILITY_SOURCE,
        final_fair_probability=fair_probability,
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
        book_probabilities=book_probabilities,
        calculated_at=calculated_at,
        pricing_gate_failures=tuple(failures),
        consensus_fair_point=consensus_fair_point,
        line_advantage=line_advantage,
        push_probability=push_probability,
        loss_probability=loss_probability,
        market_probability_policy_version=market_probability_policy_version,
        market_curve_artifact_hash=market_curve_artifact_hash,
        center_dispersion=center_dispersion,
    )


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
        selection_american_odds=selected_observation.american_odds,
        selection_point=selected_observation.point,
        selection_observed_at=selected_observation.observed_at,
    )


def _projected_book_price(
    item: _PairedBookMarket,
    side: str,
    candidate_point: Decimal,
    curve: EmpiricalMarketCurve,
    book_center: Decimal,
) -> BookNoVigPrice:
    opposing = _opposing_side(item.market_type, side)
    selected_observation = item.observations[side]
    opposing_observation = item.observations[opposing]
    settlement = curve.settlement(book_center, candidate_point, side)  # type: ignore[arg-type]
    return BookNoVigPrice(
        sportsbook_key=item.sportsbook_key,
        sportsbook_name=item.sportsbook_name,
        selection_probability=settlement.win,
        opposing_probability=settlement.loss,
        raw_probability_sum=item.raw_probability_sum,
        overround=item.overround,
        selection_observation_id=selected_observation.observation_id,
        opposing_observation_id=opposing_observation.observation_id,
        snapshot_ids=tuple(
            sorted(
                {selected_observation.snapshot_id, opposing_observation.snapshot_id},
                key=str,
            )
        ),
        selection_american_odds=selected_observation.american_odds,
        selection_point=selected_observation.point,
        selection_observed_at=selected_observation.observed_at,
    )


def _one_main_pair_per_book(book_markets: list[_PairedBookMarket]) -> list[_PairedBookMarket]:
    by_book: dict[str, list[_PairedBookMarket]] = defaultdict(list)
    for item in book_markets:
        by_book[item.sportsbook_key].append(item)
    if all(len(items) == 1 for items in by_book.values()):
        return sorted(book_markets, key=lambda item: item.sportsbook_key)
    reference_points = sorted(_pair_reference_point(item) for item in book_markets)
    reference = (
        reference_points[len(reference_points) // 2]
        if len(reference_points) % 2
        else (
            reference_points[len(reference_points) // 2 - 1]
            + reference_points[len(reference_points) // 2]
        )
        / Decimal(2)
    )
    selected = [
        min(
            items,
            key=lambda item: (
                abs(_pair_reference_point(item) - reference),
                abs(item.overround),
                item.line_key,
            ),
        )
        for items in by_book.values()
    ]
    return sorted(selected, key=lambda item: item.sportsbook_key)


def _pair_reference_point(item: _PairedBookMarket) -> Decimal:
    first_side = _expected_sides(item.market_type)[0]
    point = item.observations[first_side].point
    if point is None:
        return Decimal(0)
    return -point if item.market_type == "spread" else point


def _source_ids(
    book_markets: list[_PairedBookMarket],
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
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
    return source_ids, snapshot_ids


def _line_advantage(
    market_type: str,
    side: str,
    center: Decimal,
    point: Decimal,
) -> Decimal:
    if market_type == "spread":
        return center + point if side == "home" else -center + point
    return center - point if side == "over" else point - center


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
