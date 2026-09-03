from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# BUILD_SPEC F3 - Option B (maker-quoting). The whale ONLY selects which
# markets/brackets to quote; we quote our OWN post-only limits around fair.
DEFAULT_CONFIG: dict = {
    # Proven bracket MM (+16% ROI playbook; $473k live portfolio verified 2026-07-06)
    "whale_wallet": "0xd218e474776403a330142299f7796e8ba32eb5c9",
    "lookback_hours": 12,          # whale activity window that marks a bracket "active"
    "bid_margin_below_fair": 0.02,
    "kelly_fraction": 0.15,        # smaller than S2 - whale signal, not our model
    "max_bet_pct": 0.05,
    "min_edge_threshold": 0.02,
    "aggregate_price_ceiling": 0.65,
    # The aggregate ceiling only guarantees a winner when the basket covers EVERY
    # bracket. Applied to a PARTIAL basket it is not a hedge, it is a concentrated
    # bet: 8 brackets of one auction summing 0.639 all resolved worthless on
    # 2026-08-04 (-$35.99 in a day) because the winner sat outside the set. Bound
    # how much of one auction the whale can pull us into.
    "max_brackets_per_auction": 3,
    "whale_perf_gate_roi": -0.30,  # bench the whale if last-10 ROI worse than this
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
