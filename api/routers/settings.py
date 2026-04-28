from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from api.dependencies import get_supabase
from api.routers.modules import ModuleConfigUpdate
from api.config import get_settings
from api.services.profiles import (
    get_active_profile, list_profiles, save_profile,
    switch_profile, delete_profile, set_multi_exec, get_multi_exec_profiles,
    strip_credentials, strip_credentials_list,
)

router = APIRouter()


class RiskSettingsUpdate(BaseModel):
    """Bounds-checked. paper_mode/shadow_mode are read at boot from ENV; setting
    them via this endpoint is a dead write — removed to avoid false sense of
    control (flagged in 2026-04-27 QA pass)."""
    bankroll: float | None = Field(default=None, ge=0)
    max_portfolio_exposure: float | None = Field(default=None, ge=0, le=1)
    max_single_market_exposure: float | None = Field(default=None, ge=0, le=1)
    max_correlated_exposure: float | None = Field(default=None, ge=0, le=1)
    daily_loss_limit: float | None = Field(default=None, ge=0, le=0.5)
    weekly_loss_limit: float | None = Field(default=None, ge=0, le=0.5)
    max_drawdown: float | None = Field(default=None, ge=0, le=0.5)
    min_edge_threshold: float | None = Field(default=None, ge=0, le=0.5)
    slippage_tolerance: float | None = Field(default=None, ge=0, le=0.2)
    kelly_fraction: float | None = Field(default=None, ge=0, le=1)
    circuit_breaker_enabled: bool | None = None
    circuit_breaker_max_consecutive_losses: int | None = Field(default=None, ge=1, le=20)
    circuit_breaker_cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)


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


# Defaults applied on first read so the channel toggles always exist.
NOTIFICATION_DEFAULTS = {
    "enabled": True,        # global toggle; back-compat with prior code
    "slack_enabled": True,  # master kill for Slack channel
    "email_enabled": False, # email path not yet wired (Option A); default OFF
}


@router.get("/notifications")
async def get_notification_settings():
    sb = get_supabase()
    res = sb.table("settings").select("value").eq("key", "notifications").execute()
    stored = (res.data[0].get("value") or {}) if res.data else {}
    # Backfill defaults so the dashboard always sees the channel-toggle keys.
    return {**NOTIFICATION_DEFAULTS, **stored}


class NotificationSettingsUpdate(BaseModel):
    """Slack webhook URL must point at an official Slack webhook host so a
    misconfig or compromised dashboard cannot exfiltrate trade data to an
    attacker-controlled URL. Empty string is allowed (disables Slack).

    `slack_enabled` and `email_enabled` are master kill switches per channel.
    When False, no notification of that type fires regardless of per-event
    toggles (e.g. divergence_alerts_enabled).
    """
    slack_webhook: str | None = None
    discord_webhook: str | None = None
    enabled: bool | None = None
    slack_enabled: bool | None = None
    email_enabled: bool | None = None
    email_address: str | None = None

    @field_validator("slack_webhook")
    @classmethod
    def validate_slack(cls, v: str | None) -> str | None:
        if not v:
            return v
        if not v.startswith("https://hooks.slack.com/"):
            raise ValueError("slack_webhook must start with https://hooks.slack.com/")
        return v

    @field_validator("discord_webhook")
    @classmethod
    def validate_discord(cls, v: str | None) -> str | None:
        if not v:
            return v
        if not (v.startswith("https://discord.com/api/webhooks/") or v.startswith("https://discordapp.com/api/webhooks/")):
            raise ValueError("discord_webhook must point at discord.com/api/webhooks/")
        return v

    @field_validator("email_address")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if not v:
            return v
        # Cheap shape check; full RFC validation isn't needed for our use case.
        if "@" not in v or "." not in v.split("@", 1)[1]:
            raise ValueError("email_address must be a valid email")
        return v

    model_config = {"extra": "ignore"}


@router.put("/notifications")
async def update_notification_settings(config: NotificationSettingsUpdate):
    """Merge the provided fields onto whatever's already stored, so a partial
    update (e.g. PUT {slack_enabled: false}) doesn't wipe webhook URLs."""
    sb = get_supabase()
    existing_row = sb.table("settings").select("value").eq("key", "notifications").execute()
    existing = (existing_row.data[0].get("value") or {}) if existing_row.data else {}
    merged = {**NOTIFICATION_DEFAULTS, **existing, **config.model_dump(exclude_unset=True)}
    sb.table("settings").upsert({"key": "notifications", "value": merged}).execute()
    return merged


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
async def update_module_config(module_id: str, config: "ModuleConfigUpdate"):
    from api.modules.truth_social.module_config import save_module_config
    payload = config.model_dump(exclude_unset=True)
    save_module_config(module_id, payload)
    return {"ok": True}


@router.get("/profiles/multi-status")
async def get_multi_status():
    profiles = get_multi_exec_profiles()
    return {
        "enabled_count": len(profiles),
        "active": len(profiles) > 1,
        "profiles": [{"name": p["name"], "wallet_address": p.get("wallet_address", "")} for p in profiles],
    }
