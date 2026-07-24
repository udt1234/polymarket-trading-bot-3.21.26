"""Ornstein-Uhlenbeck mean-reversion estimation (pure stdlib).

The standard quant model for a mean-reverting series:

    dP_t = theta * (mu - P_t) dt + sigma dW_t

Discretised, the increments regress linearly on the level:

    P_{t+1} - P_t = a + b * P_t + eps      with   b = -theta*dt,  mu = -a/b

From that: theta = -b/dt, half-life = ln(2)/theta (how long a shock takes to decay
halfway back to mu), and sigma_eq = the equilibrium (stationary) standard deviation
used to z-score the current level.

theta <= 0 means the series is NOT mean-reverting (it trends or random-walks) - the
caller must refuse to trade it. A half-life that is implausibly short is microstructure
noise (bid-ask bounce), and one longer than the trading horizon is untradeable.

Shared so every module + backtest fits the SAME estimator (no copy-paste drift).
"""
import math


def fit_ou(prices: list, dt_minutes: float = 1.0) -> dict | None:
    """OLS fit of the discretised OU process. Returns
    {theta, mu, sigma_eq, halflife_min, n} or None if unusable."""
    n = len(prices)
    if n < 10 or dt_minutes <= 0:
        return None
    x = prices[:-1]           # level at t
    y = [prices[i + 1] - prices[i] for i in range(n - 1)]  # increment
    m = len(x)
    sx = sum(x); sy = sum(y)
    sxx = sum(v * v for v in x); sxy = sum(x[i] * y[i] for i in range(m))
    denom = m * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None
    b = (m * sxy - sx * sy) / denom
    a = (sy - b * sx) / m
    if b >= 0:
        return None  # not mean-reverting (theta <= 0)
    theta = -b / dt_minutes
    if theta <= 0:
        return None
    mu = -a / b
    # residual variance -> equilibrium sigma of the OU
    resid = [y[i] - (a + b * x[i]) for i in range(m)]
    var_e = sum(r * r for r in resid) / max(1, m - 2)
    # stationary variance of OU: sigma_eq^2 = var_eps / (1 - (1+b)^2)
    phi = 1.0 + b
    denom2 = 1.0 - phi * phi
    if denom2 <= 1e-12:
        return None
    sigma_eq = math.sqrt(max(var_e / denom2, 1e-12))
    halflife = math.log(2.0) / theta  # in the same time units as dt_minutes
    return {"theta": theta, "mu": mu, "sigma_eq": sigma_eq,
            "halflife_min": halflife, "n": n}


def zscore(price: float, fit: dict) -> float | None:
    """How many equilibrium sigma the current price sits above (+) or below (-)
    its OU mean. This is the fade signal."""
    if not fit or fit.get("sigma_eq", 0) <= 0:
        return None
    return (price - fit["mu"]) / fit["sigma_eq"]
