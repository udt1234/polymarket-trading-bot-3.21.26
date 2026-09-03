from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# ELON LAST-6H ARBITRAGE SCANNER (paper test, 2026-07-24).
#
# Two distinct arbs, both scanned on the LIVE Elon tweet-count auction in its final
# window. This is different from the existing arb_scanner (which reads a fixed Gamma
# tag + TAKER asks only and can only find complete-set-below-$1, proven ~dead):
#
#   A) COMPLETE-SET TAKER ARB: sum of best_ask over ALL brackets < 1 - margin. Exactly
#      one bracket pays $1, so buying every leg at ask is riskless. This is the ONE
#      case the maker-only bot is allowed to TAKE (a true simultaneous complete set).
#      Rare on a liquid book (ask-sum = 1 + spread) but appears on stale/fragmented
#      late books - which is exactly what Sir saw and we were not scanning.
#
#   B) COMPLEMENT-PAIR MAKER ARB (the audit's validated edge, below $1 on 100% of bars
#      across 22 auctions): within ONE bracket, rest a post-only BID on YES and a BID
#      on NO whose prices sum < 1 - margin. If BOTH fill you hold YES+NO = guaranteed
#      $1 for less than $1 = locked profit + maker rebate on both legs. RISK: only one
#      leg fills -> directional. Paper measures the real both-legs-fill rate honestly.
DEFAULT_CONFIG: dict = {
    "window_hours": 6.0,          # only scan inside the final N hours
    "set_margin": 0.01,           # complete-set fires when ask-sum < 1 - this
    "pair_margin": 0.02,          # complement-pair fires when bid-sum target < 1 - this
    "per_arb_max_usd": 50.0,      # stake per detected arb
    "max_concurrent": 6,
    "min_leg_price": 0.02,
    "max_leg_price": 0.98,
    "min_notional": 1.0,
    # arb edge is structural (locked below $1), not a directional fair-value gap
    "gate_min_edge": 0.0,
    "gate_spread_tol": 0.20,
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
