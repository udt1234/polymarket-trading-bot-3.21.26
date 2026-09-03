from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# BUILD_SPEC F2 config keys.
DEFAULT_CONFIG: dict = {
    "auction_duration": "2-day",       # which live auction S2 quotes
    "kelly_fraction": 0.25,
    "max_bet_pct": 0.15,
    "aggregate_price_ceiling": 0.65,
    "num_brackets": 3,
    "bid_margin_below_fair": 0.03,     # absolute (cents), not % - QA 2026-07-03
    "min_edge_threshold": 0.02,
    "slippage_tolerance": 0.05,
    "salvage_exit_threshold": 0.03,
    "take_profit_pct": 0.0,            # off - hold to resolution
    "stop_loss_pct": 0.0,              # off
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
