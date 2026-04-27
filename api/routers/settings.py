from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.dependencies import get_supabase
from api.config import get_settings
from api.services.profiles import (
    get_active_profile, list_profiles, save_profile,
    switch_profile, delete_profile, set_multi_exec, get_multi_exec_profiles,
    strip_credentials, strip_credentials_list,
)

router = APIRouter()


class RiskSettingsUpdate(BaseModel):
    bankroll: float | None = None
    max_portfolio_exposure: float | None = None
    max_single_market_exposure: float | None = None
    max_correlated_exposure: float | None = None
    daily_loss_limit: float | None = None
    weekly_loss_limit: float | None = None
    max_drawdown: float | None = None
    min_edge_threshold: float | None = None
    slippage_tolerance: float | None = None
    kelly_fraction: float | None = None
    circuit_breaker_enabled: bool | None = None
    circuit_breaker_max_consecutive_losses: int | None = None
    circuit_breaker_cooldown_minutes: int | None = None
    shadow_mode: bool | None = None
    paper_mode: bool | None = None


class ProfileCreate(BaseModel):
    name: str
    wallet_address: str = ""
    polymarket_api_key: str = ""
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""
    polymarket_private_key: str = ""
    multi_exec: bool = False


class MultiExecToggle(BaseModel):
    enabled: bool


@router.get("/risk")
async def get_risk_settings():
    sb = get_supabase()
    res = sb.table("settings").select("*").eq("key", "risk").single().execute()
    return res.data.get("value", {}) if res.data else {}


@router.put("/risk")
async def update_risk_settings(update: RiskSettingsUpdate):
    sb = get_supabase()
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    sb.table("settings").upsert({"key": "risk", "value": data}).execute()
    return data


@router.get("/circuit-breaker")
async def get_circuit_breaker_state():
    from api.services.engine import engine
    return engine.risk_manager.get_circuit_breaker_state()


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker():
    from api.services.engine import engine
    engine.risk_manager.reset_circuit_breaker()
    return {"ok": True, "state": engine.risk_manager.get_circuit_breaker_state()}


@router.get("/statistical-tests")
async def get_statistical_tests():
    sb = get_supabase()
    res = sb.table("statistical_tests").select("*").execute()
    return res.data


@router.post("/statistical-tests")
async def add_statistical_test(test_config: dict):
    sb = get_supabase()
    res = sb.table("statistical_tests").insert(test_config).execute()
    return res.data[0]


@router.get("/notifications")
async def get_notification_settings():
    sb = get_supabase()
    res = sb.table("settings").select("*").eq("key", "notifications").single().execute()
    return res.data.get("value", {}) if res.data else {}


@router.put("/notifications")
async def update_notification_settings(config: dict):
    sb = get_supabase()
    sb.table("settings").upsert({"key": "notifications", "value": config}).execute()
    return config


# --- Wallet/Profile Management ---

@router.get("/profiles")
async def get_profiles():
    # Never return raw Polymarket credentials in API responses. The dashboard
    # only needs to know whether a profile has creds configured (`has_credentials`).
    return {
        "profiles": strip_credentials_list(list_profiles()),
        "active": strip_credentials(get_active_profile()),
    }


@router.post("/profiles")
async def create_profile(profile: ProfileCreate):
    save_profile(profile.model_dump())
    return {"ok": True}


@router.put("/profiles/{name}/activate")
async def activate_profile(name: str):
    try:
        profile = switch_profile(name)
        return {"ok": True, "profile": strip_credentials(profile)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/profiles/{name}")
async def remove_profile(name: str):
    try:
        delete_profile(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Multi-Account Execution ---

@router.put("/profiles/{name}/multi-exec")
async def toggle_multi_exec(name: str, body: MultiExecToggle):
    try:
        profile = set_multi_exec(name, body.enabled)
        from api.services.engine import engine
        if engine._running:
            engine.reload_executors()
        return {"ok": True, "profile": profile["name"], "multi_exec": profile["multi_exec"]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reset-paper-trades")
async def reset_paper_trades():
    sb = get_supabase()
    settings = get_settings()
    if not settings.paper_mode:
        raise HTTPException(status_code=400, detail="Can only reset in paper mode")

    sb.table("positions").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("trades").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("orders").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("signals").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("daily_pnl").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    sb.table("calibration_log").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    return {"ok": True, "message": "All paper trading data cleared"}


# --- Module Config ---

@router.get("/module-configs")
async def get_all_module_configs():
    sb = get_supabase()
    modules = sb.table("modules").select("id,name,status").in_("status", ["active", "paused", "paper"]).execute()
    from api.modules.truth_social.module_config import get_module_config
    result = []
    for m in modules.data or []:
        cfg = get_module_config(m["id"])
        result.append({"module_id": m["id"], "name": m["name"], "status": m["status"], "config": cfg})
    return result


@router.get("/module-configs/{module_id}")
async def get_module_config_endpoint(module_id: str):
    from api.modules.truth_social.module_config import get_module_config
    return get_module_config(module_id)


@router.put("/module-configs/{module_id}")
async def update_module_config(module_id: str, config: dict):
    from api.modules.truth_social.module_config import save_module_config
    save_module_config(module_id, config)
    return {"ok": True}


@router.get("/profiles/multi-status")
async def get_multi_status():
    profiles = get_multi_exec_profiles()
    return {
        "enabled_count": len(profiles),
        "active": len(profiles) > 1,
        "profiles": [{"name": p["name"], "wallet_address": p.get("wallet_address", "")} for p in profiles],
    }
