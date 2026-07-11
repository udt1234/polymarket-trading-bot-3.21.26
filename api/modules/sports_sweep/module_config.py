from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# Sports garbage-time sweep (backtest-validated 2026-07-10, MLB, +2-3% ROI on
# real fills+fees). Buy a DECIDED favorite's CHEAP shares as retail dumps the
# lost side, hold to resolution, cut the ~1-3% collapse games with a stop-loss.
DEFAULT_CONFIG: dict = {
    # 2-outcome US sports (no draws): 1=NFL 2=NBA 3=MLB 4=NHL. Only whichever is
    # in season returns live games. NOTE: only MLB is backtest-validated so far;
    # the others use the same mechanic but need their own OOS check before live $.
    "series_ids": [1, 2, 3, 4],
    # entry: only sweep when the favorite is truly decided, and only buy cheap.
    "decided_bid_threshold": 0.97,   # favorite bid must be >= this (raised from
                                     #   0.95 to dodge collapses; backtest shows
                                     #   collapses cluster below 0.97)
    "max_entry_price": 0.98,         # never pay above this (0.99 band is dead)
    "min_entry_price": 0.94,         # ignore too-deep asks (genuine uncertainty)
    # maker-first: rest post-only BUY bids at a deep-discount ladder below fair.
    "bid_ladder": [0.97, 0.96, 0.95],
    "per_game_max_usd": 25.0,        # cap exposure per game (fat-tail control)
    "max_concurrent_games": 8,
    # exit: HOLD TO RESOLUTION. Counterintuitive backtest result 2026-07-10:
    #   a price stop-loss makes the strategy MUCH worse (+$290 hold -> -$6,791
    #   with a bid<0.90 stop over 3 MLB dates). Baseball favorites dip below any
    #   fixed level constantly on scares that fizzle, so a price stop sells
    #   eventual WINNERS at the dip - death by a thousand cuts, far bigger than
    #   the rare full collapse. The fat-tail control is the HIGH decided
    #   threshold (0.97 skips weakly-decided collapses) + small per-game size,
    #   NOT a stop-loss. A future game-STATE-aware exit (score/inning) may help.
    "stop_loss_enabled": False,      # keep OFF - price stops bleed winners
    "stop_loss_bid": 0.50,           # (only used if enabled; deep catastrophe backstop)
    "stop_loss_is_taker": True,
    "take_to_resolution": True,
    "min_edge": 0.015,               # require price below true win-rate estimate
    "decided_winrate": 0.985,        # empirical: a bid>=0.97 favorite wins ~98.5%
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
