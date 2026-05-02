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
    "manual_regime_override_default_hours": 24,
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


def _normalize_regime_override(merged: dict) -> dict:
    """Server-side guard: when an override regime is set, ensure default_hours
    is sane (1-720) and recompute expires_at if it's missing, in the past, or
    clearly bogus. Without this guard, a dashboard payload that sent 0/empty
    hours produced expires_at = now, which the bot then auto-cleared on the
    very next cycle — making the override look like it "didn't take"."""
    from datetime import datetime, timedelta, timezone
    override = (merged.get("manual_regime_override") or "").strip().upper()
    if not override:
        # No override active — clear the expiry too so we never carry a stale value.
        merged["manual_regime_override"] = ""
        merged["manual_regime_override_expires_at"] = ""
        return merged
    # Override is active. Clamp hours to [1, 720]. Treat 0 / None / non-numeric as 24.
    raw_hours = merged.get("manual_regime_override_default_hours")
    try:
        hours = float(raw_hours) if raw_hours is not None else 24.0
    except (TypeError, ValueError):
        hours = 24.0
    if hours < 1:
        hours = 24.0
    if hours > 720:
        hours = 720.0
    merged["manual_regime_override_default_hours"] = hours
    # Validate expires_at. If missing, in the past, or unparseable, recompute as
    # now + clamped hours so the bot doesn't immediately clear the override.
    now = datetime.now(timezone.utc)
    expires_at_str = (merged.get("manual_regime_override_expires_at") or "").strip()
    needs_recompute = not expires_at_str
    if expires_at_str and not needs_recompute:
        try:
            parsed = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if parsed <= now + timedelta(minutes=1):
                needs_recompute = True
        except (ValueError, TypeError):
            needs_recompute = True
    if needs_recompute:
        new_expiry = now + timedelta(hours=hours)
        merged["manual_regime_override_expires_at"] = new_expiry.isoformat()
    return merged


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
