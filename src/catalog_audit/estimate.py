"""Design-based estimates of outcome rates, with 95% intervals.

Within a stratum, questions are independent draws (one per product) with weights w_i = 1/pi_i.
A rate is estimated with the Hajek ratio estimator, p = sum(w_i y_i) / sum(w_i), and its variance
with the usual linearisation for a with-replacement approximation:

    v(p) = n / (n - 1) * sum(w_i^2 (y_i - p)^2) / (sum w_i)^2

Across strata, rates combine with population weights W_h = N_h / sum(N_h) over the strata being
pooled (N_h = eligible pairs in stratum h), and variances add as sum(W_h^2 v_h).

Comparisons between two configurations use the same questions, so the difference is estimated on
the paired indicator d_i = y_i(A) - y_i(B), which removes the question-to-question variation that
both share.

When every sampled question in a stratum has the same outcome, its linearised variance is zero,
which would report a false certainty, and pooled over strata it would make a single event look
precisely measured. Such a stratum instead contributes the variance implied by its Wilson score
interval on the effective sample size: ((upper - p) / 1.96)^2 for a rate at 0, and the same bound
on the share of discordant questions for a difference. This is conservative for rare events.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Z = 1.959964


@dataclass(frozen=True)
class Estimate:
    rate: float
    low: float
    high: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {"rate": self.rate, "low": self.low, "high": self.high, "n": self.n}


def wilson(p: float, n_eff: float) -> tuple[float, float]:
    if n_eff <= 0:
        return 0.0, 1.0
    denom = 1 + Z**2 / n_eff
    centre = (p + Z**2 / (2 * n_eff)) / denom
    half = Z * math.sqrt(p * (1 - p) / n_eff + Z**2 / (4 * n_eff**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def hajek(y: Sequence[float], w: Sequence[float]) -> tuple[float, float, float]:
    """Return (rate, variance, effective sample size) within one stratum."""
    n = len(y)
    if n == 0:
        return math.nan, math.nan, 0.0
    sw = sum(w)
    p = sum(wi * yi for wi, yi in zip(w, y)) / sw
    if n == 1:
        return p, math.nan, 1.0
    var = n / (n - 1) * sum(wi**2 * (yi - p) ** 2 for wi, yi in zip(w, y)) / sw**2
    n_eff = sw**2 / sum(wi**2 for wi in w)
    return p, var, n_eff


def _floor_variance(p: float, n_eff: float, bounded: bool) -> float:
    """Variance for a stratum whose sampled outcomes are all identical (see the module docstring).
    For a rate, the distance to the far Wilson limit; for a difference (all zeros), the Wilson
    upper limit for 0 discordant questions."""
    if bounded:
        low, high = wilson(min(max(p, 0.0), 1.0), n_eff)
        return (max(high - p, p - low) / Z) ** 2
    _, upper = wilson(0.0, n_eff)
    return (upper / Z) ** 2


def stratified(groups: dict[str, tuple[Sequence[float], Sequence[float]]],
               population: dict[str, int], bounded: bool = True) -> Estimate:
    """groups: stratum -> (y, w). population: stratum -> N_h (eligible pairs)."""
    total = sum(population[h] for h in groups)
    rate, var, n = 0.0, 0.0, 0
    for h, (y, w) in groups.items():
        p_h, v_h, ne_h = hajek(y, w)
        share = population[h] / total
        rate += share * p_h
        if math.isnan(v_h) or v_h == 0.0:
            v_h = _floor_variance(p_h, ne_h, bounded)
        var += share**2 * v_h
        n += len(y)
    half = Z * math.sqrt(var)
    low, high = rate - half, rate + half
    if bounded:
        low, high = max(0.0, low), min(1.0, high)
    return Estimate(rate, low, high, n)
