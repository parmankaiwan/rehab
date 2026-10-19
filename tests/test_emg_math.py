import math

import numpy as np

from backend.emg_math import estimation_metrics, gauss_legendre_rule, geometry_report, simulate, slider_demo


def test_gauss_legendre_rules_are_normalized_and_polynomial_exact():
    for order in range(2, 6):
        rule = gauss_legendre_rule(order)
        assert sum(rule.average_weights) == pytest.approx(1.0)
        for degree in range(2 * order):
            estimated = sum(w * x**degree for x, w in zip(rule.nodes, rule.average_weights))
            expected = 0.0 if degree % 2 else 1.0 / (degree + 1)
            assert estimated == pytest.approx(expected, abs=1e-12)


def test_primary_three_point_rule_and_slider_contributions():
    rule = gauss_legendre_rule(3)
    assert rule.nodes == pytest.approx((-math.sqrt(3 / 5), 0.0, math.sqrt(3 / 5)))
    assert rule.average_weights == pytest.approx((5 / 18, 4 / 9, 5 / 18))
    demo = slider_demo([0.2, 1.0, 0.4])
    assert demo["arithmetic_mean"] == pytest.approx(1.6 / 3)
    assert sum(item["contribution"] for item in demo["gaussian_quadrature"]["contributions"]) == pytest.approx(demo["gaussian_quadrature"]["estimate"])


def test_simulation_uses_dense_reference_and_reports_actual_errors():
    result = simulate("CENTRAL_PEAK", 3, frames=40)
    assert result["reference"]["available"] is True
    assert result["reference"]["dense_points"] == 10001
    assert result["methods"]["GAUSSIAN_QUADRATURE"]["mae"] >= 0
    assert result["methods"]["ARITHMETIC_MEAN"]["mae"] >= 0
    assert result["comparison"]["winner"] in {"GAUSSIAN_QUADRATURE", "ARITHMETIC_MEAN", "TIE"}


def test_neither_method_is_hard_coded_as_the_winner():
    assert simulate("POLYNOMIAL", 3, frames=40)["comparison"]["winner"] == "GAUSSIAN_QUADRATURE"
    assert simulate("CENTRAL_PEAK", 3, frames=40)["comparison"]["winner"] == "ARITHMETIC_MEAN"


def test_metrics_and_geometry_do_not_invent_a_reference():
    assert estimation_metrics(np.array([1.0]), None)["available"] is False
    report = geometry_report([-0.7, 0.0, 0.7], 3)
    assert report["valid"] is True
    assert report["matches_gaussian_nodes"] is False
    assert "do not match" in report["reason"]


import pytest
