from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# ELON LAST-6H MEAN REVERSION (paper test, 2026-07-24).
#
# THESIS STATUS - READ BEFORE TRUSTING THIS: blind mean-reversion on Elon brackets is
# KNOWN-DEAD (2026-07-13 study: dips are CONTINUATION not overshoot, only 18-27% bounce
# after a >=3c dip; every blind maker fade LOST, buy-dip hold -14.18 over 276 fills,
# 6/34 auctions positive). The ONE surviving hypothesis, never fill-tested, is:
#   fade UP-spikes late in the auction, as a MAKER, ONLY on brackets the LOCKED pace
#   model says are NON-winners (losers revert +10-14c; a misclassified winner runs to
#   100c = -19c, so the pace gate is what makes or breaks it).
# This module tests EXACTLY that hypothesis and nothing looser.
#
# HOW WE FADE WITHOUT SHORTING: you cannot short a Polymarket bracket. Fading a spiked
# bracket = buying its NO token (a post-only BID on NO). That is maker-only and
# long-only, so it obeys the bot's LOCKED maker-only constraint.
#
# QUANT: Ornstein-Uhlenbeck. dP = theta*(mu - P)dt + sigma*dW. We estimate theta/mu/
# sigma by OLS on the price increments, derive half-life = ln(2)/theta, and only trade
# when (a) the series is genuinely mean-reverting (half-life inside a sane band) and
# (b) the current price is z-sigma ABOVE its OU mean.
DEFAULT_CONFIG: dict = {
    "window_hours": 6.0,        # only act inside the final N hours of the auction
    "z_entry": 2.0,             # fade when price is this many sigma above the OU mean
    "min_halflife_min": 5.0,    # reject series that revert too fast to be real (noise)
    "max_halflife_min": 240.0,  # reject series with no usable reversion inside our horizon
    "min_theta": 1e-6,          # theta<=0 means NOT mean-reverting (trending) - skip
    "min_obs": 30,              # need this many price points to fit the OU
    "max_pace_prob": 0.15,      # PACE GATE: only fade brackets the locked model gives <=15% win prob
    "size_pct": 0.02,           # fraction of module budget per fade
    "max_concurrent": 4,
    "min_no_price": 0.05,       # don't buy NO below this (dust/illiquid)
    "max_no_price": 0.90,       # don't chase an already-resolved-looking NO
    "min_notional": 1.0,
    # risk-gate overrides: the edge here is statistical reversion, not a directional
    # fair-value gap, so the 2% edge floor is the wrong test (see risk_manager._meta_float)
    "gate_min_edge": 0.0,
    "gate_spread_tol": 0.15,
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
