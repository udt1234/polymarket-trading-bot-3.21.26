"""LOCKED pace + fair-value math - the SINGLE source of truth.

This model is LOCKED (leaderboard, 144 auctions, walk-forward, 2026-07-06) and
must NOT be changed without Sir's explicit approval + a MODEL_VERSION bump. It was
previously copy-pasted (subtly divergently) across ~20 backtest scripts AND the live
bot ran an OLDER overconfident sigma (a flat *1.5) that the 2026-07-11 calibration
lesson had already superseded. Both the live modules and every backtest now import
from HERE so drift is structurally impossible and the auditor can hash one file.

Two locked pieces:
  1. Ensemble + CAP1.5 projection: Kalman early + AccrualCurve late, blended, with the
     go-forward rate CAPPED at 1.5x baseline (the cap kills burst runaway).
  2. Calibrated remaining-uncertainty sigma: calib_sigma(remaining_hours) via the
     validated interp table (real 62-auction forecast error), replacing the old
     flat sqrt(remaining)*1.5 that made odds ~2x too confident.

Pure stdlib (no numpy) so it imports anywhere. Change a locked literal here and you
must bump MODEL_VERSION; the backtest-auditor diffs RUN_META against this.
"""
import math

MODEL_VERSION = "ensemble-cap1.5+calibsigma.2026-07-11"

# --- LOCKED constants (do NOT edit without Sir's sign-off + a MODEL_VERSION bump) ---
CAP_MULT = 1.5          # go-forward rate cap = CAP_MULT * baseline hourly rate
SIGMA_MIN = 1.0         # floor on the remaining-uncertainty sigma
SIGMA_MAX = 100.0       # ceiling (was 8; raised 2026-07-11 so honest tails aren't clipped)

# Calibrated remaining-uncertainty sigma vs remaining hours (62-auction forecast error,
# 2026-07-11). rh = hours left in the auction; sd = std of the final-count forecast.
_SIG_RH = [1, 4, 8, 12, 18, 24, 32, 40, 48]
_SIG_SD = [5.0, 7.8, 10.8, 15.5, 16.8, 18.9, 31.4, 38.2, 42.0]

_SQRT2 = math.sqrt(2.0)


def _interp(x: float, xs: list, ys: list) -> float:
    """Linear interpolation with flat extrapolation (matches numpy.interp)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def calib_sigma(remaining_hours: float) -> float:
    """LOCKED calibrated sigma of the final-count forecast, clamped [SIGMA_MIN, SIGMA_MAX]."""
    return max(SIGMA_MIN, min(SIGMA_MAX, _interp(remaining_hours, _SIG_RH, _SIG_SD)))


def cap15_projection(obs: float, elapsed_h: float, remaining_h: float,
                     baseline_rate: float, kalman_gain: float,
                     accrual_share: float, cp: float) -> float:
    """LOCKED Ensemble + CAP1.5 final-count projection.

    obs           = tweets observed so far in the window
    elapsed_h     = hours elapsed, remaining_h = hours remaining
    baseline_rate = prior tweets/hour (rmean)
    kalman_gain   = Kk (from the walk-forward prior fit)
    accrual_share = median cumulative-accrual fraction at this elapsed hour (0..1]
    cp            = accrual-curve blend weight = elapsed_h / total_h (0 early -> 1 late)

    Kalman leg early, accrual leg late, blended by cp, then the per-hour go-forward
    rate is CAPPED at CAP_MULT * baseline_rate.
    """
    if elapsed_h <= 0:
        return obs + baseline_rate * remaining_h
    kalman = obs + (baseline_rate + kalman_gain * (obs / elapsed_h - baseline_rate)) * remaining_h
    accrual = obs / accrual_share if accrual_share > 0 else kalman
    ensemble = (1.0 - cp) * kalman + cp * accrual
    go_forward = min((ensemble - obs) / max(remaining_h, 0.1), CAP_MULT * baseline_rate)
    return obs + go_forward * remaining_h


def bracket_fair(lo: float, hi: float, projection: float, sigma: float) -> float:
    """Fair YES probability that the final count lands in [lo, hi] under
    Normal(projection, sigma), with the +/-0.5 integer continuity correction.
    Clamped to (1e-6, 1-1e-6). hi >= 1e8 is treated as +inf (open-ended bracket)."""
    hi_cdf = 1.0 if hi >= 1e8 else 0.5 * (1.0 + math.erf((hi + 0.5 - projection) / (sigma * _SQRT2)))
    lo_cdf = 0.5 * (1.0 + math.erf((lo - 0.5 - projection) / (sigma * _SQRT2)))
    return max(1e-6, min(1.0 - 1e-6, hi_cdf - lo_cdf))
