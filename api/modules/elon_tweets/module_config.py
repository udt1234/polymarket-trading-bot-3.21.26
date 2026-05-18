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
    # 2026-05-18: regime_modifier OFF by default for Elon. QUIET regime was
    # shrinking every Kelly bet by 10% (0.90×), pushing model edge below the
    # min_edge_threshold and silently emitting 0 signals every cycle. The
    # backtest already validated leaving it off; Sir flipped it after seeing
    # 24h of `signals=0` cycles.
    "use_signal_modifier": False,
    "use_regime_modifier": False,
    "use_hawkes_modifier": True,
    "stop_loss_pct": 0.30,
    "take_profit_pct": 0.0,
    "trailing_stop_pct": 0.30,
    "max_brackets_per_cycle": 5,
    # Lowered 2026-05-18: 0.02 was blocking every Elon signal in QUIET regime
    # because model_prob × 0.90 (regime damp) - market_price rarely cleared
    # 2¢. With regime_modifier now off AND threshold at 1¢, signals can pass.
    "min_edge_threshold": 0.01,
    "floor_brackets_by_running_total": True,
    "auction_aggregate_price_ceiling": 0.65,
    "historical_blend_weight": 0.70,
    "historical_winner_half_life_weeks": 8.0,
    "low_window_kelly_boost": 1.30,
    "pre_auction_buying_enabled": False,
    "divergence_alerts_enabled": True,
    "divergence_market_price_min": 0.20,
    "divergence_model_prob_max": 0.05,
    "divergence_cooldown_hours": 6.0,
    "manual_regime_override": "",
    "manual_regime_override_expires_at": "",
    "manual_regime_override_default_hours": 1,
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
    """Persist a partial config update without resetting other fields.
    See api/modules/truth_social/module_config.py for the full rationale.
    """
    from api.modules.shared.module_config_utils import normalize_regime_override
    sb = get_supabase()
    key = f"module_config:{module_id}"
    existing_row = sb.table("settings").select("value").eq("key", key).execute()
    stored = (existing_row.data[0].get("value") or {}) if existing_row.data else {}
    merged = {**DEFAULT_CONFIG, **stored, **(config or {})}
    merged = normalize_regime_override(merged)
    sb.table("settings").upsert({"key": key, "value": merged}).execute()
