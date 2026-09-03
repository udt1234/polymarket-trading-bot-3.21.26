"""The modeling brain: projection + bracket fair values (BUILD_SPEC D1-D3).

We do NOT try to out-forecast the market; this is the ruler we measure
deals against. Validated priors (playbook): Elon 7-day ~207 (std ~55),
monthly median ~923; 2-day derives from the ~30/day market-counted rate.
"""
import math
import re

from api.modules.shared import locked_pace

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


_DUR_HOURS = {"2-day": 48, "7-day": 168, "monthly": 720}
_priors_cache: dict = {}


def _load_priors(handle: str, dur_h: int) -> dict | None:
    """Read stored LOCKED-model priors (fitted offline by
    scripts/compute_locked_priors.py). Cached per process; None if absent."""
    key = f"locked_pace_priors:{handle}:{dur_h}"
    if key in _priors_cache:
        return _priors_cache[key]
    try:
        from api.dependencies import get_supabase
        res = (get_supabase().table("settings").select("value")
               .eq("key", key).limit(1).execute())
        val = res.data[0]["value"] if res.data else None
    except Exception:
        val = None
    _priors_cache[key] = val
    return val


def projection(posts_so_far: int, elapsed_fraction: float, prior_mean: float,
               prior_std: float, *, duration_type: str = "2-day",
               handle: str = "elonmusk", remaining_hours: float | None = None) -> float:
    """THE projection the bot trades on. Uses the LOCKED Ensemble+CAP1.5 model when
    priors are available for this handle+duration, else falls back to the older
    Gamma-Poisson blend. Locked model = Kalman early + accrual curve late, blended,
    with the go-forward rate capped at 1.5x baseline (LOCKED 2026-07-06)."""
    dur_h = _DUR_HOURS.get(duration_type, 48)
    pri = _load_priors(handle, dur_h)
    if pri:
        elapsed_h = max(0.0, min(1.0, elapsed_fraction)) * dur_h
        rem_h = remaining_hours if remaining_hours is not None else max(0.0, dur_h - elapsed_h)
        got = locked_pace.project_locked(posts_so_far, elapsed_h, rem_h, pri)
        if got is not None:
            return got
    return gamma_poisson_projection(posts_so_far, elapsed_fraction, prior_mean, prior_std)


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
                         labels: list[str], remaining_hours: float | None = None) -> dict[str, float]:
    """Fair win probability per bracket (D3).

    - Final count ~ Normal(projection, sigma). sigma is the LOCKED calibrated
      remaining-uncertainty (locked_pace.calib_sigma(remaining_hours), the
      62-auction forecast-error table + SIGMA_MAX=100, LOCKED 2026-07-11). This
      replaced the old flat sqrt(remaining)*1.5 that made odds ~2x too confident
      (84% at 24h, 100% at 4h). If remaining_hours is unknown (legacy callers),
      fall back to the old formula so behavior is unchanged for them.
    - Any bracket whose upper bound < posts_so_far is IMPOSSIBLE (count
      only rises) -> exactly 0.
    - Renormalized to sum 1.
    """
    if remaining_hours is not None:
        sigma = locked_pace.calib_sigma(remaining_hours)
    else:
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
