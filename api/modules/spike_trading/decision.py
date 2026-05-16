"""HOLD / SELL / SELL-NOW classifier for spike_trading.

This is the heatmap as code. Source: 51 historical Elon 2-day <40 auctions
(see _DataMetricPulls/elon_2day_analysis/hold_signal_grid.csv).

Inputs are the current state of an open position. Output is one of four
decisions, in priority order:

  SELL-NOW   — bracket is dying, dump immediately at market.
               Triggers from cfg["sellnow_grid"]. ≥70% of historicals in
               these states ended ≤1¢.
  HOLD       — clear winner trajectory; cancel any active sell limits so
               we don't accidentally exit too early.
               Single state cell: tweets ≤ hold_max AND hours ≥ hold_min
               (median end_price was 99¢ historically, 2.4× upside).
  HOLD-LIGHT — likely-winner, but not a sure thing. Keep ladder limits but
               don't bail on a paper loss.
  SELL       — default; let the limit-sell ladder do its thing organically.

Order matters: SELL-NOW always wins, then HOLD, then HOLD-LIGHT, else SELL.
"""
from dataclasses import dataclass


@dataclass
class PositionState:
    """Snapshot of where an open position sits in the heatmap."""
    cum_tweets: int
    hours_to_close: float
    current_price: float          # latest observed YES price
    entry_price: float            # cost basis
    pnl_pct: float                # (current - entry) / entry × 100


# Legacy classifiers (classify_decision / classify_decision_v2 /
# should_market_sell / should_cancel_aggressive_tiers / trailing_stop_price)
# were removed 2026-05-16. Strategy plugins now own classification via
# `strategy.classify(state, position, params)`. Module no longer imports
# from this file's classifier API.


def adaptive_buy_price(
    best_bid: float, best_ask: float, base_target: float,
    spread_jump_eps: float = 0.001,
) -> float:
    """Smarter buy price than a hardcoded 12c.

    Logic:
      - If best_ask < base_target → buy at best_ask - eps (jump the queue
        for ~equivalent cost). E.g. ask=10c, target=12c → buy at 9.9c.
      - If best_ask >= base_target → place at base_target (limit waits).
      - Always clamps to [0.001, 0.99].
    """
    if best_ask > 0 and best_ask < base_target:
        return max(round(best_ask - spread_jump_eps, 4), 0.001)
    return min(max(base_target, 0.001), 0.99)


def adaptive_sell_ladder(
    entry_price: float, multipliers: list[float],
) -> list[float]:
    """Convert entry price + multipliers (e.g. [1.5, 2.0, 4.0, 8.0]) into
    absolute sell limit prices. Multipliers are RELATIVE to entry, so a
    9c entry → [13.5c, 18c, 36c, 72c] instead of hardcoded ladder.
    """
    return [min(round(entry_price * m, 4), 0.99) for m in multipliers]


def slow_bleed_sell_price(
    hours_to_close: float, current_bid: float, min_floor: float = 0.005,
) -> float:
    """When SELL-NOW fires but bid book is too thin to cross, walk a
    sell limit DOWN toward the floor over remaining hours.

    Strategy: place limit at (current_bid - small_step) but never below
    min_floor. Each cycle the price walks down — if any bid appears we
    fill, if not we keep walking.

    Returns the suggested limit-sell price.
    """
    if current_bid <= 0:
        # Empty book — start at 1c and decay from there
        # (closer to close = lower target)
        decay_factor = max(min(hours_to_close / 24.0, 1.0), 0.05)
        return max(round(0.01 * decay_factor, 4), min_floor)
    # Bid exists but is below SELLNOW_MIN_BID floor — sit just below it
    return max(round(current_bid - 0.001, 4), min_floor)
