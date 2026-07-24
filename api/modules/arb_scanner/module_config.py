from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# ARB SCANNER (fixed 2026-07-24). Two structural arbs across every scanned event:
#   A) COMPLETE-SET TAKER: sum of YES asks over an event's legs < 1 - margin. Exactly
#      one leg pays $1 => buying the set is riskless. The one sanctioned taker case.
#      Was 0 orders in 13 days because it computed edge as profit/n_legs (~0.003) which
#      the 2% edge floor then rejected - both fixed.
#   B) COMPLEMENT-PAIR MAKER (the edge Sir's data validates): rest a BID on YES and a
#      BID on NO of ONE market summing < 1 - margin. NO_bid = 1 - YES_ask, so a wide
#      YES spread => resting both bids locks (spread - 2 ticks) if BOTH fill. Priced
#      from Gamma's YES book, zero extra calls. RISK: only one leg fills => directional.
DEFAULT_CONFIG: dict = {
    "scan_tag": 972,                 # tweet-count multi-bracket events
    "scan_limit": 100,
    "set_margin": 0.01,              # complete-set fires when ask-sum < 1 - this
    "pair_margin": 0.02,             # complement-pair fires when locked profit >= this
    "max_legs": 40,
    "per_arb_max_usd": 25.0,
    "min_leg_price": 0.02,
    "max_leg_price": 0.98,
    "max_signals": 20,
    "min_notional": 1.0,
    # structural arb, not a directional fair-value gap: opt out of the 2% edge floor
    # (this was THE reason it never fired).
    "gate_min_edge": 0.0,
    "gate_spread_tol": 0.30,
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
