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
    "divergence_alerts_enabled": True,
    "divergence_market_price_min": 0.20,
    "divergence_model_prob_max": 0.05,
    "divergence_cooldown_hours": 6.0,
    # Manual regime override — operator forces a regime when they disagree with
    # the statistical detector. Empty string = no override. Valid values:
    # "NORMAL", "QUIET", "LOW", "HIGH", "SURGE", "TRANSITION".
    # `manual_regime_override_expires_at` is an ISO 8601 timestamp. When set
    # and in the past, the override is considered expired and the bot reverts
    # to the detector. The override row is also cleared so the dashboard
    # reflects the auto-revert. Default override duration when set via dashboard
    # is `manual_regime_override_default_hours` (24h by default).
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


from api.modules.shared.module_config_utils import normalize_regime_override as _normalize_regime_override


def save_module_config(module_id: str, config: dict):
    """Persist a partial config update without resetting other fields.

    Prior implementation merged the incoming `config` over `DEFAULT_CONFIG`
    every save, which silently reset every previously-customized field
    (min_edge_threshold, stop_loss_pct, etc.) when the caller only sent one
    field. Now we read the stored value first and merge `config` over that;
    DEFAULT_CONFIG only fills in keys that have never been set.

    Also normalizes the manual_regime_override block so a payload with
    missing/zero hours doesn't produce an expiry in the past that the bot
    would auto-clear on the next cycle.
    """
    sb = get_supabase()
    key = f"module_config:{module_id}"
    existing_row = sb.table("settings").select("value").eq("key", key).execute()
    stored = (existing_row.data[0].get("value") or {}) if existing_row.data else {}
    merged = {**DEFAULT_CONFIG, **stored, **(config or {})}
    merged = _normalize_regime_override(merged)
    sb.table("settings").upsert({"key": key, "value": merged}).execute()
