"""Spike Rider config. Stored in `settings` table under key `module_config:{module_id}`.

Defaults match the offline simulator winner: multi-stage exits at 2x/3x/5x with
a $10 entry size, conservative entry-price band, and the same fee/slippage
assumptions used in the report.
"""
from api.dependencies import get_supabase

DEFAULT_CONFIG = {
    # Entry
    "entry_size_usd": 10.0,            # fixed dollar size per bracket
    "entry_min_price": 0.02,           # skip brackets priced below this (dust)
    "entry_max_price": 0.40,           # skip already-rich brackets
    "max_open_positions": 5,           # ceiling across all brackets
    "max_open_per_auction": 3,         # ceiling within a single auction
    "elapsed_max_pct": 0.50,           # don't enter past this fraction of auction elapsed
    "focus_brackets": [],              # optional allowlist; empty = all eligible
    # Sell rule selection
    "sell_rule_type": "multi_stage",   # one of: multi_stage | target_multiplier | trailing_stop
    # multi_stage params
    "sell_multi_stage_targets": [2.0, 3.0, 5.0],   # multiplier -> sell 1/N each time hit
    # target_multiplier params
    "sell_target_multiplier": 2.0,
    # trailing_stop params (used as a *backup* exit even when multi_stage selected)
    "sell_trail_pct": 0.30,            # sell when price drops this much from peak
    "sell_min_gain_pct": 0.50,         # only arm trailing stop after this much gain
    # Cost model (inform sizing decisions; executor still owns real fills)
    "fee_pct": 0.02,
    "slippage_pct": 0.05,
    # Operational
    "enabled": True,
    "auto_pause_after_losses": 5,
}


def get_module_config(module_id: str) -> dict:
    sb = get_supabase()
    key = f"module_config:{module_id}"
    res = sb.table("settings").select("*").eq("key", key).execute()
    if res.data:
        stored = res.data[0].get("value", {}) or {}
        return {**DEFAULT_CONFIG, **stored}
    return dict(DEFAULT_CONFIG)


def save_module_config(module_id: str, config: dict):
    """Merge-on-save so partial updates don't clobber unrelated fields."""
    sb = get_supabase()
    key = f"module_config:{module_id}"
    existing = sb.table("settings").select("value").eq("key", key).execute()
    stored = (existing.data[0].get("value") or {}) if existing.data else {}
    merged = {**DEFAULT_CONFIG, **stored, **(config or {})}
    sb.table("settings").upsert({"key": key, "value": merged}).execute()
