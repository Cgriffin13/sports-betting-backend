from decimal import Decimal

import pytest

from app.domain.pricing import (
    VIG_REMOVAL_POLICY_VERSION,
    american_odds_to_decimal,
    american_odds_to_implied_probability,
    decimal_odds_to_implied_probability,
    expected_value_binary,
    expected_value_with_push,
    probability_edge,
    remove_vig_proportionally,
    unweighted_median_consensus,
)


def test_positive_and_negative_american_odds_convert_exactly() -> None:
    assert american_odds_to_decimal(150) == Decimal("2.5")
    assert american_odds_to_decimal(-200) == Decimal("1.5")
    assert american_odds_to_implied_probability(150) == Decimal("0.4")
    assert american_odds_to_implied_probability(-200) == Decimal(2) / Decimal(3)


@pytest.mark.parametrize("odds", [0, 99, -99])
def test_invalid_american_odds_are_rejected(odds: int) -> None:
    with pytest.raises(ValueError, match="American odds"):
        american_odds_to_decimal(odds)


@pytest.mark.parametrize("odds", [Decimal("1"), Decimal("0"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_decimal_odds_are_rejected(odds: Decimal) -> None:
    with pytest.raises(ValueError, match="Decimal odds"):
        decimal_odds_to_implied_probability(odds)


def test_decimal_implied_probability_is_exact() -> None:
    assert decimal_odds_to_implied_probability(Decimal("2.5")) == Decimal("0.4")


def test_two_way_proportional_vig_removal_reports_overround_and_normalizes() -> None:
    raw = (
        american_odds_to_implied_probability(-110),
        american_odds_to_implied_probability(-110),
    )

    result = remove_vig_proportionally(raw)

    assert result.policy_version == VIG_REMOVAL_POLICY_VERSION
    assert result.raw_probability_sum == Decimal(22) / Decimal(21)
    assert result.overround == result.raw_probability_sum - Decimal(1)
    assert result.probabilities == (Decimal("0.5"), Decimal("0.5"))
    assert sum(result.probabilities) == Decimal(1)


def test_vig_removal_rejects_incomplete_or_invalid_probability_sets() -> None:
    with pytest.raises(ValueError, match="at least two"):
        remove_vig_proportionally((Decimal("0.5"),))
    with pytest.raises(ValueError, match="greater than zero"):
        remove_vig_proportionally((Decimal("0"), Decimal("0.5")))
    with pytest.raises(ValueError, match="between 0 and 1"):
        remove_vig_proportionally((Decimal("1.1"), Decimal("0.5")))


def test_unweighted_median_consensus_reports_dispersion_and_outliers() -> None:
    result = unweighted_median_consensus(
        (Decimal("0.50"), Decimal("0.51"), Decimal("0.60")),
        outlier_threshold=Decimal("0.05"),
    )

    assert result.probability == Decimal("0.51")
    assert result.dispersion == Decimal("0.10")
    assert result.outlier_indexes == (2,)
    assert result.policy_version == "unweighted-median-v1"


def test_edge_and_binary_ev_are_distinct_and_exact() -> None:
    fair = Decimal("0.55")
    offered = american_odds_to_implied_probability(110)
    decimal_odds = american_odds_to_decimal(110)

    assert probability_edge(fair, offered) == fair - offered
    assert expected_value_binary(fair, decimal_odds) == Decimal("0.155")


def test_push_capable_ev_requires_explicit_win_and_loss_probabilities() -> None:
    assert expected_value_with_push(Decimal("0.50"), Decimal("0.45"), Decimal("2.0")) == Decimal("0.05")
    with pytest.raises(ValueError, match="sum above 1"):
        expected_value_with_push(Decimal("0.60"), Decimal("0.50"), Decimal("2.0"))
