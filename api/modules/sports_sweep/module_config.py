from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# Sports garbage-time sweep (backtest-validated 2026-07-10, MLB, +2-3% ROI on
# real fills+fees). Buy a DECIDED favorite's CHEAP shares as retail dumps the
# lost side, hold to resolution, cut the ~1-3% collapse games with a stop-loss.
DEFAULT_CONFIG: dict = {
    "series_ids": [3],               # 3=MLB (2=NBA,4=NHL,1=NFL when in season)
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
    # exit: cut the loss if the favorite fades (comebacks are gradual, sellable).
    "stop_loss_bid": 0.85,           # sell out if the favorite's bid falls below
    "stop_loss_is_taker": True,      # cross to the bid to guarantee the exit
    "take_to_resolution": True,      # else hold winners to $1
    "min_edge": 0.015,               # require price below true win-rate estimate
    "decided_winrate": 0.985,        # empirical: a bid>=0.97 favorite wins ~98.5%
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
