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
    # No volume threshold (removed 2026-05-05 per user). For limit-only
    # entries, illiquidity doesn't matter: a 12c limit either fills at 12c
    # or doesn't fill at all. Exit-side liquidity is handled separately
    # by the SELLNOW_MIN_BID guard.
    "min_market_volume_24h": 0,
    # Polymarket Series slug — primary discovery path. Surfaces auctions as
    # soon as Polymarket lists them, before xTracker starts counting tweets.
    # Find via gamma-api.polymarket.com/series?slug=<x> or by inspecting the
    # 'series' field on any /events response.
    "series_slug": "elon-tweets-48h",

    # ---- Buy ladder ----
    # Tier 1 at 12¢: aggressive entry meant to capture the auction WHILE it
    #   still looks "alive" on Polymarket (per user override 2026-05-05).
    #   Historical 12¢ floor hit-rate is ~98% (almost every 2-day <40 has
    #   touched 12¢ at some point), but on most paths price never returns
    #   to <1¢ — so a high floor catches more positions at the cost of
    #   higher avg entry.
    # Tier 2 at 0.5¢: kept as a "if it ever crashes, scoop the lottery
    #   ticket" cheap re-entry. Historical hit-rate ~96%.
    "buy_tier_1_price": 0.12,                 # 12¢ — aggressive primary entry
    "buy_tier_1_pct":   0.50,
    "buy_tier_2_price": 0.005,                # 0.5¢ — cheap re-entry if crash
    "buy_tier_2_pct":   0.50,
    "buy_cancel_after_hours": 24,

    # ---- Sell ladder (RELATIVE to entry, not hardcoded prices) ----
    # Multipliers are applied to actual fill price, so a 9c fill -> 13.5/18/36/72
    # whereas a 12c fill -> 18/24/48/96 (capped at 99c). This is much smarter
    # than hardcoded sells because the same multiplier-based ladder works
    # whether we filled cheap or expensive.
    "sell_multipliers": [1.5, 2.0, 4.0, 8.0],
    "sell_multiplier_pcts": [0.30, 0.30, 0.20, 0.20],

    # ---- Take-profit / stop-loss / trailing-stop (consumed by exit_manager) ----
    # These fire AUTOMATICALLY at the position level — no manual intervention.
    # take_profit_pct: exit when price up this fraction above avg fill (e.g.
    #   0.50 = exit at 1.5× entry; 1.50 = exit at 2.5× entry)
    # stop_loss_pct: exit when price down this fraction below avg fill
    #   (0.60 = exit at 40% of entry. Spike is lottery-ticket so we tolerate
    #    deep drawdown — the SELL-NOW classifier handles the "bracket
    #    busting" case faster than a generic stop-loss would.)
    # trailing_stop_pct: when up >50%, lock in by trailing the stop this far
    #   below the running peak.
    "take_profit_pct": 7.0,                   # +700% (8x — moonshot)
    "stop_loss_pct": 0.85,                    # -85% (deep — strategy expects losers)
    "trailing_stop_pct": 0.30,                # 30% trail behind peak

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

    # ---- Pacing-aware overrides (classify_decision_v2) ----
    # pacing_score = projected_final_tweets / bracket_max_count (40 for <40).
    #   < 0.30 → bracket clearly NOT going to bust — hold even if other
    #            signals say sell.
    #   >= 1.20 → bracket clearly busting — SELL-NOW even if other signals
    #            say hold. Only fires after first 20% of window elapsed
    #            (avoids extrapolating from 0 elapsed hours).
    "bracket_max_count": 40,                  # the "<40" boundary
    "pacing_sell_score": 1.20,
    "pacing_hold_score": 0.30,

    # ---- Risk ----
    "bracket_cap_pct_of_bankroll": 0.05,      # 5% per cycle max (lottery ticket sizing)
    "max_open_positions": 3,                  # cap concurrent positions

    # ---- Operational ----
    # shadow_mode=True means decisions are logged but NOT routed to the
    # executor at all. False means the module emits real Signals; whether
    # they trade paper or live is determined by the engine's env PAPER_MODE.
    # Default False so a module with DB status='paper' will paper-trade.
    "shadow_mode": False,
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
