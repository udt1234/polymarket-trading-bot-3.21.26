"""Spike Trading module config.

Defaults are calibrated from 51 historical Elon 2-day <40 auctions
(see _DataMetricPulls/elon_2day_analysis/decision_brief.md). Re-run
the analysis whenever you add a new month of data and tune these
thresholds in this dict.
"""
from api.dependencies import get_supabase

DEFAULT_CONFIG = {
    # ---- Discovery ----
    "platform": "x",                          # 'x' for Elon, 'truthsocial' for Trump
    "handle": "elonmusk",
    "window_days": 2,                         # only trade 2-day auctions
    "bracket_pattern": "<40",                 # which bracket label to trade
    "min_market_volume_24h": 50_000,          # skip illiquid markets

    # ---- Buy ladder ----
    # Limit-buy at 0.5¢ for half allocation, 0.3¢ for the other half.
    # 96-98% of past auctions traded at-or-below 1¢ at some point.
    "buy_tier_1_price": 0.005,                # 0.5¢
    "buy_tier_1_pct":   0.50,
    "buy_tier_2_price": 0.003,                # 0.3¢
    "buy_tier_2_pct":   0.50,
    "buy_cancel_after_hours": 24,

    # ---- Sell ladder ----
    # Hit rates from historical data:
    #   3¢  -> 85% of auctions
    #   7¢  -> 61%
    #  15¢  -> 41%
    #  30¢+ -> 20%
    "sell_tier_1_price": 0.03,                # 3¢   - lock-in tier
    "sell_tier_1_pct":   0.25,
    "sell_tier_2_price": 0.07,                # 7¢
    "sell_tier_2_pct":   0.25,
    "sell_tier_3_price": 0.15,                # 15¢
    "sell_tier_3_pct":   0.25,
    "sell_tier_4_price": 0.30,                # 30¢ - moonshot
    "sell_tier_4_pct":   0.25,

    # ---- HOLD signal (don't liquidate even if up 5x) ----
    # Validated against 51 markets — only ONE state cell qualifies as a clean HOLD.
    "hold_max_tweets": 5,                     # ≤ this many tweets in window
    "hold_min_hours_remaining": 24,           # ≥ this many hours left

    # ---- SELL-NOW grid (liquidate immediately, bracket is dying) ----
    # ≥70% of historicals in these states ended ≤1¢.
    # Each entry is (min_cumulative_tweets, min_hours_remaining_when_triggered).
    "sellnow_grid": [
        [16, 24],                             # 16+ tweets with 24+ hours left
        [20, 18],                             # 20+ tweets with 18+ hours left
        [30, 0],                              # 30+ tweets at any time
    ],

    # ---- Risk ----
    "bracket_cap_pct_of_bankroll": 0.05,      # 5% per cycle max (lottery ticket sizing)
    "stop_loss_pct": -0.5,                    # bail if down 50% before SELL-NOW triggers
    "max_open_positions": 3,                  # cap concurrent positions

    # ---- Operational ----
    "shadow_mode": True,                      # PHASE 1 default: log only, don't trade
    "log_decisions_to_supabase": True,        # write spike_state_snapshots
}


def get_module_config(module_id: str) -> dict:
    sb = get_supabase()
    key = f"module_config:{module_id}"
    res = sb.table("settings").select("*").eq("key", key).execute()
    if res.data:
        stored = res.data[0].get("value", {})
        return {**DEFAULT_CONFIG, **stored}
    return dict(DEFAULT_CONFIG)


def save_module_config(module_id: str, config: dict):
    """Partial-update without resetting other fields."""
    sb = get_supabase()
    key = f"module_config:{module_id}"
    existing_row = sb.table("settings").select("value").eq("key", key).execute()
    stored = (existing_row.data[0].get("value") or {}) if existing_row.data else {}
    merged = {**DEFAULT_CONFIG, **stored, **(config or {})}
    sb.table("settings").upsert({"key": key, "value": merged}).execute()
