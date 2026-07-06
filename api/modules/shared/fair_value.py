"""The modeling brain: projection + bracket fair values (BUILD_SPEC D1-D3).

We do NOT try to out-forecast the market; this is the ruler we measure
deals against. Validated priors (playbook): Elon 7-day ~207 (std ~55),
monthly median ~923; 2-day derives from the ~30/day market-counted rate.
"""
import math
import re

VALIDATED_PRIORS = {  # duration_type -> (prior_mean, prior_std)
    "2-day": (60.0, 25.0),
    "7-day": (207.0, 55.0),
    "monthly": (923.0, 250.0),
}


def gamma_poisson_projection(posts_so_far: int, elapsed_fraction: float,
                             prior_mean: float, prior_std: float) -> float:
    """Bayesian Gamma-Poisson blend (D2). Beats naive linear extrapolation
    (5 tweets in hour 1 must not predict 840/week). elapsed_fraction is
    floored 0.001 / capped 0.99 upstream (windows.elapsed_fraction)."""
    elapsed = min(max(elapsed_fraction, 0.001), 0.99)
    obs_projection = posts_so_far / elapsed
    prior_precision = 1.0 / max(prior_std ** 2, 1e-9)
    # Poisson: var(total/elapsed) ~ posts/elapsed^2, so precision grows as
    # the window fills and the observed pace takes over from the prior.
    obs_precision = elapsed ** 2 / max(posts_so_far, 1.0)
    return ((prior_precision * prior_mean + obs_precision * obs_projection)
            / (prior_precision + obs_precision))


_RANGE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
_LESS_RE = re.compile(r"(?:less than|<|under)\s*(\d+)", re.I)
_MORE_RE = re.compile(r"(\d+)\s*(?:\+|or more)", re.I)


def parse_bracket_range(label: str) -> tuple[int, float] | None:
    """'less than 40' -> (0, 39); '40-49' -> (40, 49); '180+' -> (180, inf)."""
    label = label.strip()
    m = _LESS_RE.search(label)
    if m:
        return (0, int(m.group(1)) - 1)
    m = _RANGE_RE.search(label)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = _MORE_RE.search(label)
    if m:
        return (int(m.group(1)), math.inf)
    return None


def _norm_cdf(x: float, mean: float, std: float) -> float:
    return 0.5 * (1.0 + math.erf((x - mean) / (std * math.sqrt(2.0))))


def bracket_distribution(projection: float, posts_so_far: int,
                         labels: list[str]) -> dict[str, float]:
    """Fair win probability per bracket (D3).

    - Final count ~ Normal(projection, sigma) with the validated
      remaining-uncertainty sigma: sqrt(max(projection - posts_so_far, 1))
      * 1.5. This single formula was the fix that took near-close Brier
      from 0.41 to 0.13; it already shrinks as the window ends because
      projection - posts_so_far shrinks, so no extra time-shrink factor
      is applied on top (double-shrinking underweights the tails).
    - Any bracket whose upper bound < posts_so_far is IMPOSSIBLE (count
      only rises) -> exactly 0.
    - Renormalized to sum 1.
    """
    sigma = math.sqrt(max(projection - posts_so_far, 1.0)) * 1.5
    probs: dict[str, float] = {}
    for label in labels:
        rng = parse_bracket_range(label)
        if rng is None:
            probs[label] = 0.0
            continue
        lo, hi = rng
        if hi < posts_so_far:
            probs[label] = 0.0
            continue
        lo_eff = max(lo, posts_so_far)  # mass below the current count is dead
        hi_cdf = 1.0 if hi == math.inf else _norm_cdf(hi + 0.5, projection, sigma)
        p = hi_cdf - _norm_cdf(lo_eff - 0.5, projection, sigma)
        probs[label] = max(p, 0.0)
    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}
    return probs


def edge(fair: float, price: float | None) -> float | None:
    """Edge per share = fair value minus market price (D4)."""
    return None if price is None else fair - price
