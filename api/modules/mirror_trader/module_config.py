from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# Mirror-copytrader (Option A): follow proven whales' BUYS as a resting maker,
# sized down, across ANY market (not tweet-scoped like the copytrader module).
# Whales chosen 2026-07-13 by COPYABILITY (diversified + active + currently
# WINNING + small positions), NOT raw leaderboard profit - the top-profit
# mega-whales had live books down 32-63% and unclonable position sizes.
DEFAULT_CONFIG: dict = {
    "whale_wallets": [
        "0xd218e474776403a330142299f7796e8ba32eb5c9",  # +103% live book, 190 pos / 79 mkts, very active
        "0x714a685b5454ea4d52979563bbafa77b8168ab2f",  # pada: +92% live book, focused, persistent 30d+7d
    ],
    "lookback_hours": 24,          # mirror buys the whale made in this window
    "whale_perf_gate_roi": 0.0,    # only mirror a whale whose live book is GREEN
    "size_pct": 0.02,              # fraction of bankroll per mirrored bet
    "max_markets": 10,             # cap concurrent mirrored positions
    "max_price": 0.90,             # don't chase near-resolved favorites
    "min_notional": 1.0,
    # risk-gate overrides (copy strategy, not directional edge - see module.py).
    # whale_perf_gate_roi above is the real gate; this just removes the wrong one.
    "gate_min_edge": 0.0,          # following a green whale is the thesis, not edge
    "gate_spread_tol": 0.15,       # copy across arbitrary (sometimes wide) markets
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
