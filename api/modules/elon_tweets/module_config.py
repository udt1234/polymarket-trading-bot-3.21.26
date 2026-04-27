from api.dependencies import get_supabase

DEFAULT_CONFIG = {
    "historical_periods": 9,
    "auto_optimize_periods": True,
    "recency_half_life": 4.0,
    "use_regime_conditional": True,
    "use_parquet_model": True,
    "confidence_band_top_n": 3,
    "pacing_display_days_prior": 10,
    "pacing_display_days_future": 7,
    "dow_weights_source": "recency",
    "enabled_models": ["pace", "bayesian", "dow", "historical", "hawkes"],
    "strategy_preset": "full",
    "entry_gate_pct": 0.0,
    "use_signal_modifier": False,
    "use_regime_modifier": True,
    "use_hawkes_modifier": True,
    "stop_loss_pct": 0.30,
    "take_profit_pct": 0.0,
    "trailing_stop_pct": 0.30,
    "max_brackets_per_cycle": 5,
    "min_edge_threshold": 0.02,
    "floor_brackets_by_running_total": True,
    "auction_aggregate_price_ceiling": 0.65,
    "historical_blend_weight": 0.70,
    "historical_winner_half_life_weeks": 8.0,
    "low_window_kelly_boost": 1.30,
    "pre_auction_buying_enabled": False,
    "wait_for_dip_enabled": True,
    "wait_min_drop_threshold": 0.05,
    "wait_max_days": 3.0,
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
    sb = get_supabase()
    key = f"module_config:{module_id}"
    merged = {**DEFAULT_CONFIG, **config}
    sb.table("settings").upsert({"key": key, "value": merged}).execute()
