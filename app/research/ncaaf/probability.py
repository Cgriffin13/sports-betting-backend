from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

import numpy as np
from scipy import stats
from scipy.ndimage import gaussian_filter1d

CALIBRATION_VERSION = "ncaaf-distribution-calibration-v1"
NORMAL_VERSION = "normal-homoskedastic-v1"
STUDENT_T_VERSION = "student-t-bounded-grid-v1"
EMPIRICAL_VERSION = "empirical-kernel-v1"
HETEROSKEDASTIC_VERSION = "quality-grouped-scale-v1"
SKEW_NORMAL_VERSION = "skew-normal-total-v1"
MIN_SCALE = 0.25
PROBABILITY_EPSILON = 1e-12
STUDENT_DF_GRID = (3.0, 5.0, 8.0, 15.0, 30.0)
SKEW_SHAPE_GRID = (-8.0, -4.0, -2.0, -1.0, 0.0, 1.0, 2.0, 4.0, 8.0)


class PredictiveDistribution(Protocol):
    @property
    def family(self) -> str: ...
    @property
    def location(self) -> float: ...
    @property
    def scale(self) -> float: ...

    def cdf(self, value: float) -> float: ...
    def pdf(self, value: float) -> float: ...
    def ppf(self, probability: float) -> float: ...
    def parameters(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class NormalDistribution:
    location: float
    scale: float
    family: str = NORMAL_VERSION

    def __post_init__(self) -> None:
        _validate_location_scale(self.location, self.scale)

    def cdf(self, value: float) -> float:
        return _probability(stats.norm.cdf(value, loc=self.location, scale=self.scale))

    def pdf(self, value: float) -> float:
        return max(PROBABILITY_EPSILON, float(stats.norm.pdf(value, loc=self.location, scale=self.scale)))

    def ppf(self, probability: float) -> float:
        return float(stats.norm.ppf(_open_probability(probability), loc=self.location, scale=self.scale))

    def parameters(self) -> Mapping[str, Any]:
        return {"location": self.location, "scale": self.scale}


@dataclass(frozen=True, slots=True)
class StudentTDistribution:
    location: float
    scale: float
    degrees_of_freedom: float
    family: str = STUDENT_T_VERSION

    def __post_init__(self) -> None:
        _validate_location_scale(self.location, self.scale)
        if not math.isfinite(self.degrees_of_freedom) or self.degrees_of_freedom <= 2:
            raise ValueError("Student-t degrees of freedom must exceed two")

    def cdf(self, value: float) -> float:
        return _probability(stats.t.cdf(value, self.degrees_of_freedom, loc=self.location, scale=self.scale))

    def pdf(self, value: float) -> float:
        return max(
            PROBABILITY_EPSILON,
            float(stats.t.pdf(value, self.degrees_of_freedom, loc=self.location, scale=self.scale)),
        )

    def ppf(self, probability: float) -> float:
        return float(
            stats.t.ppf(
                _open_probability(probability),
                self.degrees_of_freedom,
                loc=self.location,
                scale=self.scale,
            )
        )

    def parameters(self) -> Mapping[str, Any]:
        return {
            "location": self.location,
            "scale": self.scale,
            "degrees_of_freedom": self.degrees_of_freedom,
        }


@dataclass(frozen=True, slots=True)
class SkewNormalDistribution:
    location: float
    scale: float
    shape: float
    family: str = SKEW_NORMAL_VERSION

    def __post_init__(self) -> None:
        _validate_location_scale(self.location, self.scale)
        if not math.isfinite(self.shape):
            raise ValueError("skew-normal shape must be finite")

    def cdf(self, value: float) -> float:
        return _probability(stats.skewnorm.cdf(value, self.shape, loc=self.location, scale=self.scale))

    def pdf(self, value: float) -> float:
        return max(
            PROBABILITY_EPSILON,
            float(stats.skewnorm.pdf(value, self.shape, loc=self.location, scale=self.scale)),
        )

    def ppf(self, probability: float) -> float:
        return float(stats.skewnorm.ppf(_open_probability(probability), self.shape, loc=self.location, scale=self.scale))

    def parameters(self) -> Mapping[str, Any]:
        return {"location": self.location, "scale": self.scale, "shape": self.shape}


@dataclass(frozen=True, slots=True)
class EmpiricalGridDistribution:
    location: float
    scale: float
    residual_grid: np.ndarray
    residual_cdf: np.ndarray
    residual_pdf: np.ndarray
    pool_id: str
    bandwidth: float
    family: str = EMPIRICAL_VERSION

    def __post_init__(self) -> None:
        _validate_location_scale(self.location, self.scale)
        if len(self.residual_grid) < 3 or not (
            len(self.residual_grid) == len(self.residual_cdf) == len(self.residual_pdf)
        ):
            raise ValueError("empirical grid arrays are invalid")

    def cdf(self, value: float) -> float:
        return _probability(np.interp(value - self.location, self.residual_grid, self.residual_cdf, left=0, right=1))

    def pdf(self, value: float) -> float:
        return max(
            PROBABILITY_EPSILON,
            float(np.interp(value - self.location, self.residual_grid, self.residual_pdf, left=0, right=0)),
        )

    def ppf(self, probability: float) -> float:
        return self.location + float(
            np.interp(_open_probability(probability), self.residual_cdf, self.residual_grid)
        )

    def parameters(self) -> Mapping[str, Any]:
        return {
            "location": self.location,
            "scale": self.scale,
            "pool_id": self.pool_id,
            "bandwidth": self.bandwidth,
        }


@dataclass(frozen=True, slots=True)
class SettlementProbabilities:
    win: float
    push: float
    loss: float
    audit: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        values = (self.win, self.push, self.loss)
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in values):
            raise ValueError("settlement probabilities must be finite and within [0, 1]")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-10):
            raise ValueError("settlement probabilities must sum to one")


def fit_normal(residuals: Sequence[float]) -> tuple[float, float]:
    values = _residual_array(residuals)
    return float(np.mean(values)), max(MIN_SCALE, float(np.std(values)))


def fit_student_t(residuals: Sequence[float]) -> tuple[float, float, float]:
    values = _residual_array(residuals)
    location = float(np.mean(values))
    variance = max(MIN_SCALE**2, float(np.var(values)))
    candidates: list[tuple[float, float, float]] = []
    for degrees in STUDENT_DF_GRID:
        scale = max(MIN_SCALE, math.sqrt(variance * (degrees - 2.0) / degrees))
        nll = float(-np.mean(stats.t.logpdf(values, degrees, loc=location, scale=scale)))
        candidates.append((nll, degrees, scale))
    _, degrees, scale = min(candidates)
    return location, scale, degrees


def fit_skew_normal(residuals: Sequence[float]) -> tuple[float, float, float]:
    values = _residual_array(residuals)
    mean = float(np.mean(values))
    variance = max(MIN_SCALE**2, float(np.var(values)))
    candidates: list[tuple[float, float, float, float, float]] = []
    for shape in SKEW_SHAPE_GRID:
        delta = shape / math.sqrt(1 + shape**2)
        scale = max(MIN_SCALE, math.sqrt(variance / max(1e-6, 1 - 2 * delta**2 / math.pi)))
        location = mean - scale * delta * math.sqrt(2 / math.pi)
        nll = float(-np.mean(stats.skewnorm.logpdf(values, shape, loc=location, scale=scale)))
        candidates.append((nll, abs(shape), shape, location, scale))
    _, _, shape, location, scale = min(candidates)
    return location, scale, shape


def fit_empirical_grid(residuals: Sequence[float], *, pool_id: str) -> EmpiricalGridDistribution:
    values = _residual_array(residuals)
    scale = max(MIN_SCALE, float(np.std(values)))
    bandwidth = max(0.35, 1.06 * scale * len(values) ** (-0.2))
    lower = math.floor(float(np.min(values)) - 4 * bandwidth)
    upper = math.ceil(float(np.max(values)) + 4 * bandwidth)
    step = 0.25
    edges = np.arange(lower - step / 2, upper + step, step)
    counts, _ = np.histogram(values, bins=edges)
    density = gaussian_filter1d(counts.astype(float), sigma=bandwidth / step, mode="constant")
    density /= max(PROBABILITY_EPSILON, float(np.sum(density) * step))
    grid = (edges[:-1] + edges[1:]) / 2
    cdf = np.cumsum(density) * step
    cdf = np.clip(cdf / cdf[-1], 0, 1)
    return EmpiricalGridDistribution(
        location=0.0,
        scale=scale,
        residual_grid=grid,
        residual_cdf=cdf,
        residual_pdf=density,
        pool_id=pool_id,
        bandwidth=bandwidth,
    )


def grouped_scale(
    residuals: Sequence[float],
    group_labels: Sequence[str],
    *,
    pseudo_observations: int = 200,
) -> tuple[float, float, Mapping[str, float]]:
    values = _residual_array(residuals)
    if len(values) != len(group_labels):
        raise ValueError("residuals and group labels must align")
    location, global_scale = fit_normal(values.tolist())
    global_variance = global_scale**2
    scales: dict[str, float] = {}
    labels = np.asarray(group_labels)
    for label in sorted(set(group_labels)):
        selected = values[labels == label]
        group_variance = float(np.var(selected)) if len(selected) > 1 else global_variance
        variance = (len(selected) * group_variance + pseudo_observations * global_variance) / (
            len(selected) + pseudo_observations
        )
        scales[label] = max(MIN_SCALE, math.sqrt(variance))
    return location, global_scale, scales


def quality_group(*, week: int | None, home_pbp_coverage: float | None, away_pbp_coverage: float | None) -> str:
    early = int(week or 0) <= 3
    high_quality = float(home_pbp_coverage or 0) >= 0.8 and float(away_pbp_coverage or 0) >= 0.8
    return f"{'early' if early else 'later'}|{'high' if high_quality else 'low'}"


def moneyline_probabilities(distribution: PredictiveDistribution) -> SettlementProbabilities:
    away = distribution.cdf(-0.5)
    tie = max(0.0, distribution.cdf(0.5) - away)
    home = max(0.0, 1.0 - distribution.cdf(0.5))
    non_tie = home + away
    if non_tie <= 0:
        raise ValueError("moneyline distribution has no non-tie mass")
    return _settlement(home / non_tie, 0.0, away / non_tie, audit={"conditioned_tie_mass": tie})


def spread_probabilities(distribution: PredictiveDistribution, home_line: float) -> SettlementProbabilities:
    _finite_line(home_line)
    threshold = -home_line
    if _is_integer(threshold):
        integer = round(threshold)
        loss = distribution.cdf(integer - 0.5)
        push = distribution.cdf(integer + 0.5) - loss
        win = 1.0 - distribution.cdf(integer + 0.5)
        return _settlement(win, push, loss)
    boundary = math.floor(threshold) + 0.5
    loss = distribution.cdf(boundary)
    return _settlement(1.0 - loss, 0.0, loss)


def total_probabilities(distribution: PredictiveDistribution, line: float, *, over: bool = True) -> SettlementProbabilities:
    _finite_line(line)
    if _is_integer(line):
        integer = round(line)
        under = distribution.cdf(integer - 0.5)
        push = distribution.cdf(integer + 0.5) - under
        over_probability = 1.0 - distribution.cdf(integer + 0.5)
    else:
        boundary = math.floor(line) + 0.5
        under = distribution.cdf(boundary)
        push = 0.0
        over_probability = 1.0 - under
    if over:
        return _settlement(over_probability, push, under)
    return _settlement(under, push, over_probability)


def integer_mass(distribution: PredictiveDistribution, integer: int) -> float:
    return max(0.0, distribution.cdf(integer + 0.5) - distribution.cdf(integer - 0.5))


def continuous_scores(distribution: PredictiveDistribution, actual: float) -> Mapping[str, float]:
    nll = -math.log(max(PROBABILITY_EPSILON, distribution.pdf(actual)))
    probabilities = np.linspace(0.01, 0.99, 99)
    quantiles = np.asarray([distribution.ppf(float(probability)) for probability in probabilities])
    errors = actual - quantiles
    pinball = np.where(errors >= 0, probabilities * errors, (probabilities - 1) * errors)
    crps = float(2 * np.trapezoid(pinball, probabilities))
    return {"nll": nll, "crps": crps, "pit": distribution.cdf(actual)}


def interval_diagnostics(distribution: PredictiveDistribution, actual: float) -> Mapping[str, Mapping[str, float]]:
    result: dict[str, Mapping[str, float]] = {}
    for level in (0.50, 0.80, 0.90, 0.95):
        tail = (1 - level) / 2
        lower, upper = distribution.ppf(tail), distribution.ppf(1 - tail)
        result[str(level)] = {
            "covered": float(lower <= actual <= upper),
            "width": upper - lower,
            "lower": lower,
            "upper": upper,
        }
    return result


def binary_scores(probability: float, outcome: bool) -> Mapping[str, float]:
    probability = _open_probability(probability)
    actual = float(outcome)
    return {
        "brier": (probability - actual) ** 2,
        "log_loss": -(actual * math.log(probability) + (1 - actual) * math.log(1 - probability)),
    }


def multiclass_scores(probabilities: SettlementProbabilities, outcome: str) -> Mapping[str, float]:
    if outcome not in {"win", "push", "loss"}:
        raise ValueError("outcome must be win, push, or loss")
    values = {"win": probabilities.win, "push": probabilities.push, "loss": probabilities.loss}
    brier = sum((value - float(name == outcome)) ** 2 for name, value in values.items())
    return {"brier": brier, "log_loss": -math.log(max(PROBABILITY_EPSILON, values[outcome]))}


def _settlement(win: float, push: float, loss: float, *, audit: Mapping[str, float] | None = None) -> SettlementProbabilities:
    values = np.clip(np.asarray([win, push, loss], dtype=float), 0, 1)
    total = float(np.sum(values))
    if total <= 0:
        raise ValueError("settlement probability mass is zero")
    values /= total
    return SettlementProbabilities(float(values[0]), float(values[1]), float(values[2]), audit)


def _residual_array(residuals: Sequence[float]) -> np.ndarray:
    values = np.asarray(residuals, dtype=float)
    if len(values) < 2 or not np.all(np.isfinite(values)):
        raise ValueError("residual sample must contain at least two finite values")
    return values


def _validate_location_scale(location: float, scale: float) -> None:
    if not math.isfinite(location):
        raise ValueError("distribution location must be finite")
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("distribution scale must be finite and positive")


def _probability(value: float) -> float:
    if not math.isfinite(float(value)):
        raise ValueError("probability calculation was non-finite")
    return float(np.clip(value, 0, 1))


def _open_probability(value: float) -> float:
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ValueError("probability must be finite and within [0, 1]")
    return float(np.clip(value, PROBABILITY_EPSILON, 1 - PROBABILITY_EPSILON))


def _finite_line(value: float) -> None:
    if not math.isfinite(value):
        raise ValueError("line must be finite")


def _is_integer(value: float) -> bool:
    return math.isclose(value, round(value), abs_tol=1e-10)
