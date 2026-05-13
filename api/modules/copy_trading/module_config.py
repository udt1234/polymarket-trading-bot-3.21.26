"""Copy Trading module config.

Per-module config is stored in settings.value as `module_config:{module_id}`.
The wallet list lives in the `copy_trade_wallets` table — NOT in this config —
so the dashboard can add/edit wallets without rewriting the whole config blob.
"""
from api.dependencies import get_supabase


DEFAULT_CONFIG = {
    "poll_interval_sec": 30,
    "max_trade_age_sec": 300,
    "max_price_drift_pct": 20.0,
    "per_wallet_cap_pct": 5.0,
    "per_trade_cap_pct": 1.0,
    "daily_loss_circuit_pct": -2.0,
    "whale_perf_gate_window": 10,
    "whale_perf_gate_min_roi_pct": -30.0,
    "shadow_mode": True,
}


def get_module_config(module_id: str) -> dict:
    sb = get_supabase()
    key = f"module_config:{module_id}"
    res = sb.table("settings").select("*").eq("key", key).execute()
    if res.data:
        stored = res.data[0].get("value", {}) or {}
        return {**DEFAULT_CONFIG, **stored}
    return dict(DEFAULT_CONFIG)


def save_module_config(module_id: str, config: dict) -> None:
    sb = get_supabase()
    key = f"module_config:{module_id}"
    existing_row = sb.table("settings").select("value").eq("key", key).execute()
    stored = (existing_row.data[0].get("value") or {}) if existing_row.data else {}
    merged = {**DEFAULT_CONFIG, **stored, **(config or {})}
    sb.table("settings").upsert({"key": key, "value": merged}).execute()
