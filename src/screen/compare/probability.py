"""Pre-comparison probability from assertion-derived Uniform priors.

The probability A beats B before the operator compares them is computed from the
independent priors on each opening's dimension value. It deliberately uses *no*
comparison data, so it stays the same regardless of which comparisons are selected for
the next fit.
"""

from __future__ import annotations


def _point_vs_point(mean_a: float, mean_b: float) -> float:
    if mean_a > mean_b:
        return 1.0
    if mean_a < mean_b:
        return 0.0
    return 0.5


def _point_vs_uniform(point: float, low: float, high: float) -> float:
    if point <= low:
        return 0.0
    if point >= high:
        return 1.0
    return (point - low) / (high - low)


def _uniform_vs_uniform(low_a: float, high_a: float, low_b: float, high_b: float) -> float:
    if low_a >= high_b:
        return 1.0
    if high_a <= low_b:
        return 0.0

    overlap_low = max(low_a, low_b)
    overlap_high = min(high_a, high_b)
    area = (
        0.5 * (overlap_high * overlap_high - overlap_low * overlap_low)
        - low_b * (overlap_high - overlap_low)
        + max(0.0, high_a - overlap_high) * (high_b - low_b)
    )
    return min(max(area / ((high_a - low_a) * (high_b - low_b)), 0.0), 1.0)


def pre_comparison_probability(
    mean_a: float,
    half_width_a: float,
    mean_b: float,
    half_width_b: float,
) -> float:
    """P(X_a > X_b) for X_a~U(mean_a ± half_width_a), X_b~U(mean_b ± half_width_b)."""
    if half_width_a <= 0.0 and half_width_b <= 0.0:
        return _point_vs_point(mean_a, mean_b)

    low_a, high_a = mean_a - half_width_a, mean_a + half_width_a
    low_b, high_b = mean_b - half_width_b, mean_b + half_width_b

    if half_width_a <= 0.0:
        return _point_vs_uniform(mean_a, low_b, high_b)
    if half_width_b <= 0.0:
        return 1.0 - _point_vs_uniform(mean_b, low_a, high_a)

    return _uniform_vs_uniform(low_a, high_a, low_b, high_b)
