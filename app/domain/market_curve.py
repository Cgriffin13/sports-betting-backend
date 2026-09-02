from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, Mapping

MARKET_CURVE_POLICY_VERSION = "ncaaf-empirical-cross-line-v1"
ROBUST_CENTER_POLICY_VERSION = "overround-weighted-huber-center-v1"
PROBABILITY_QUANTUM = Decimal("0.000000000001")

Market = Literal["spread", "total"]
Side = Literal["home", "away", "over", "under"]


@dataclass(frozen=True, slots=True)
class SettlementProbability:
    win: Decimal
    push: Decimal
    loss: Decimal

    def __post_init__(self) -> None:
        if any(not value.is_finite() or value < 0 or value > 1 for value in (self.win, self.push, self.loss)):
            raise ValueError("Settlement probabilities must be finite and within [0, 1]")
        if abs(self.win + self.push + self.loss - Decimal(1)) > PROBABILITY_QUANTUM:
            raise ValueError("Settlement probabilities must sum to one")

    @property
    def conditional_win(self) -> Decimal:
        resolved = self.win + self.loss
        return self.win / resolved if resolved else Decimal(0)


@dataclass(frozen=True, slots=True)
class BookCurvePoint:
    sportsbook_key: str
    center: Decimal
    overround: Decimal


@dataclass(frozen=True, slots=True)
class RobustMarketCenter:
    center: Decimal
    center_dispersion: Decimal
    outlier_sportsbooks: tuple[str, ...]
    policy_version: str = ROBUST_CENTER_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class EmpiricalMarketCurve:
    market: Market
    residual_histogram: tuple[tuple[Decimal, int], ...]
    sample_size: int
    source_seasons: tuple[int, ...]
    version: str = MARKET_CURVE_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.market not in {"spread", "total"}:
            raise ValueError("Empirical market curve supports spread or total")
        if self.sample_size < 1 or sum(count for _, count in self.residual_histogram) != self.sample_size:
            raise ValueError("Empirical residual histogram count mismatch")
        if any(not residual.is_finite() or count < 1 for residual, count in self.residual_histogram):
            raise ValueError("Empirical residual histogram is invalid")

    def settlement(self, center: Decimal, point: Decimal, side: Side) -> SettlementProbability:
        if not center.is_finite() or not point.is_finite():
            raise ValueError("Market center and point must be finite")
        expected_sides = {"spread": {"home", "away"}, "total": {"over", "under"}}
        if side not in expected_sides[self.market]:
            raise ValueError("Selection side does not match empirical market curve")
        win = Decimal(0)
        push = Decimal(0)
        loss = Decimal(0)
        for residual, count in self.residual_histogram:
            continuous = center + residual
            lower = continuous.to_integral_value(rounding=ROUND_FLOOR)
            upper = lower + Decimal(1)
            upper_weight = continuous - lower
            lower_weight = Decimal(1) - upper_weight
            for outcome, weight in ((lower, lower_weight), (upper, upper_weight)):
                mass = Decimal(count) * weight
                result = _settlement_result(self.market, side, outcome, point)
                if result > 0:
                    win += mass
                elif result < 0:
                    loss += mass
                else:
                    push += mass
        total = Decimal(self.sample_size)
        values = [value / total for value in (win, push, loss)]
        values[-1] = Decimal(1) - values[0] - values[1]
        return SettlementProbability(*values)

    def infer_center(self, point: Decimal, first_side_probability: Decimal) -> Decimal:
        if not first_side_probability.is_finite() or not Decimal(0) < first_side_probability < Decimal(1):
            raise ValueError("No-vig probability must be strictly between zero and one")
        first_side: Side = "home" if self.market == "spread" else "over"
        return _infer_center_cached(self, point, first_side, first_side_probability)


@dataclass(frozen=True, slots=True)
class MarketCurveArtifact:
    curves: Mapping[str, EmpiricalMarketCurve]
    artifact_hash: str
    source_market_dataset_hash: str
    source_feature_dataset_hash: str
    version: str


def probability_edge_with_push(
    win_probability: Decimal,
    push_probability: Decimal,
    offered_implied_probability: Decimal,
) -> Decimal:
    values = (win_probability, push_probability, offered_implied_probability)
    if any(not value.is_finite() or value < 0 or value > 1 for value in values):
        raise ValueError("Probability inputs must be finite and within [0, 1]")
    loss = Decimal(1) - win_probability - push_probability
    if loss < 0:
        raise ValueError("Win and push probabilities cannot exceed one")
    resolved = win_probability + loss
    return win_probability / resolved - offered_implied_probability if resolved else -offered_implied_probability


def robust_market_center(points: tuple[BookCurvePoint, ...], *, outlier_distance: Decimal) -> RobustMarketCenter:
    if len(points) < 2:
        raise ValueError("Robust market center requires at least two books")
    if not outlier_distance.is_finite() or outlier_distance < 0:
        raise ValueError("Outlier distance must be finite and nonnegative")
    ordered = sorted(points, key=lambda item: (item.center, item.sportsbook_key))
    base_weights = tuple(_overround_weight(item.overround) for item in ordered)
    total_weight = sum(base_weights, Decimal(0))
    halfway = total_weight / Decimal(2)
    running = Decimal(0)
    weighted_median = ordered[-1].center
    for item, weight in zip(ordered, base_weights, strict=True):
        running += weight
        if running >= halfway:
            weighted_median = item.center
            break
    deviations = tuple(abs(item.center - weighted_median) for item in ordered)
    mad = _decimal_median(deviations)
    cutoff = max(Decimal("0.5"), Decimal("2.2239") * mad)
    influenced = tuple(
        weight * min(Decimal(1), cutoff / deviation) if deviation else weight
        for weight, deviation in zip(base_weights, deviations, strict=True)
    )
    center = sum(
        (item.center * weight for item, weight in zip(ordered, influenced, strict=True)),
        Decimal(0),
    ) / sum(influenced, Decimal(0))
    return RobustMarketCenter(
        center=center.quantize(Decimal("0.000000001")),
        center_dispersion=max(item.center for item in ordered) - min(item.center for item in ordered),
        outlier_sportsbooks=tuple(
            sorted(item.sportsbook_key for item in ordered if abs(item.center - center) > outlier_distance)
        ),
    )


@lru_cache(maxsize=1)
def load_market_curve_artifact() -> MarketCurveArtifact:
    payload = json.loads(
        files("app.data").joinpath("ncaaf_market_curve_v1.json").read_text(encoding="utf-8")
    )
    expected_hash = str(payload.pop("artifact_hash"))
    actual_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("NCAAF market-curve artifact hash mismatch")
    if payload.get("version") != MARKET_CURVE_POLICY_VERSION:
        raise ValueError("Unsupported NCAAF market-curve artifact version")
    curves = {
        market: EmpiricalMarketCurve(
            market=market,
            residual_histogram=tuple(
                (Decimal(value), int(count)) for value, count in values["residual_histogram"]
            ),
            sample_size=int(values["sample_size"]),
            source_seasons=tuple(int(value) for value in values["source_seasons"]),
        )
        for market, values in payload["curves"].items()
    }
    if set(curves) != {"spread", "total"}:
        raise ValueError("NCAAF market-curve artifact must contain spread and total curves")
    return MarketCurveArtifact(
        curves=curves,
        artifact_hash=expected_hash,
        source_market_dataset_hash=str(payload["source_market_dataset_hash"]),
        source_feature_dataset_hash=str(payload["source_feature_dataset_hash"]),
        version=str(payload["version"]),
    )


@lru_cache(maxsize=4096)
def _infer_center_cached(
    curve: EmpiricalMarketCurve,
    point: Decimal,
    side: Side,
    target_probability: Decimal,
) -> Decimal:
    base = -point if curve.market == "spread" else point
    lower = base - Decimal(40)
    upper = base + Decimal(40)
    for _ in range(36):
        midpoint = (lower + upper) / Decimal(2)
        probability = curve.settlement(midpoint, point, side).conditional_win
        if probability < target_probability:
            lower = midpoint
        else:
            upper = midpoint
    return ((lower + upper) / Decimal(2)).quantize(Decimal("0.000000001"))


def _settlement_result(market: Market, side: Side, outcome: Decimal, point: Decimal) -> Decimal:
    if market == "spread":
        return outcome + point if side == "home" else -outcome + point
    return outcome - point if side == "over" else point - outcome


def _overround_weight(overround: Decimal) -> Decimal:
    if not overround.is_finite():
        raise ValueError("Overround must be finite")
    raw = Decimal("0.04") / max(overround, Decimal("0.02"))
    return min(Decimal(2), max(Decimal("0.5"), raw))


def _decimal_median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    return ordered[midpoint] if len(ordered) % 2 else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def artifact_hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
