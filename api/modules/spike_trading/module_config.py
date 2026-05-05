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
    # Skip illiquid markets. Lowered to 1k from 50k (2026-05-05) so we can
    # enter pre-launch auctions where the betting window has just opened
    # but volume hasn't built up yet. Real safety comes from limit-only
    # orders + per-tier sizing — illiquidity won't blow up the position,
    # it just means we may not fill.
    "min_market_volume_24h": 1_000,
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

    # ---- Sell ladder ----
    # Tuned for 12¢ entry (per user override 2026-05-05).
    # Old 3¢/7¢/15¢/30¢ ladder doesn't make sense anymore — selling at 3¢
    # after a 12¢ entry is a 75% loss. New ladder targets profitable exits
    # above entry plus a moonshot. Hit-rate from historical 2-day <40:
    #   15¢ ->  41% of auctions (lock-in profit, +25%)
    #   25¢ ->  ~28% (typical peak, +108%)
    #   50¢ ->  ~12% (rare moonshot, +317%)
    #   90¢ ->  resolves YES (+650%)
    "sell_tier_1_price": 0.15,                # 15¢ - lock-in (+25% on 12¢ entry)
    "sell_tier_1_pct":   0.30,
    "sell_tier_2_price": 0.25,                # 25¢ - typical peak (+108%)
    "sell_tier_2_pct":   0.30,
    "sell_tier_3_price": 0.50,                # 50¢ - rare moonshot (+317%)
    "sell_tier_3_pct":   0.20,
    "sell_tier_4_price": 0.90,                # 90¢ - hold-to-resolve (+650%)
    "sell_tier_4_pct":   0.20,

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
