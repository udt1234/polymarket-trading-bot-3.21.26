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


def classify_decision(state: PositionState, cfg: dict) -> str:
    """Return one of: SELL-NOW, HOLD, HOLD-LIGHT, SELL.

    Priority:
      1. SELL-NOW  (dying bracket — always wins)
      2. HOLD      (clear winner — overrides default sells)
      3. HOLD-LIGHT (likely winner — softens sells)
      4. SELL      (default — let ladder run)
    """
    tweets = state.cum_tweets
    hours = state.hours_to_close

    # 1) SELL-NOW grid — first match wins
    for entry in cfg.get("sellnow_grid", []):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        min_tweets, min_hours = entry
        if tweets >= min_tweets and hours >= min_hours:
            return "SELL-NOW"

    # 2) HOLD — single clean state from data: very few tweets, lots of time left
    if (
        tweets <= cfg.get("hold_max_tweets", 5)
        and hours >= cfg.get("hold_min_hours_remaining", 24)
    ):
        return "HOLD"

    # 3) HOLD-LIGHT — softer hold zone (data showed 6-10 tweets / 24-30h
    #    median end ≥ 30¢ in 30%+ of cases). Pulled the threshold loosely
    #    so we don't over-sell during normal early-auction noise.
    if tweets <= 10 and hours >= 18:
        return "HOLD-LIGHT"

    # 4) Default
    return "SELL"


def should_market_sell(decision: str) -> bool:
    """Only SELL-NOW triggers an immediate market exit."""
    return decision == "SELL-NOW"


def should_cancel_aggressive_tiers(decision: str) -> bool:
    """SELL state: pull T3+T4 limits because we've lost the moonshot setup."""
    return decision == "SELL"
