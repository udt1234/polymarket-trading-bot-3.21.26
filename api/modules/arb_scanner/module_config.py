from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# Complete-set (structural) arb: if you can BUY every outcome of one event for a
# combined ask total < $1, exactly one pays $1 => riskless profit. This is the
# one place TAKING is justified (the sanctioned taker exception). v1 = scan +
# paper: detect + log opportunities; live atomic execution is gated separately.
DEFAULT_CONFIG: dict = {
    "scan_tweet_tag": 972,           # Elon/tweet-count events (multi-bracket)
    "scan_sports_series": [1, 2, 3, 4],
    "min_profit": 0.01,              # require sum(asks) <= 1 - this (after fee headroom)
    "max_legs": 40,                  # skip events with more legs than this
    "per_arb_max_usd": 25.0,
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
