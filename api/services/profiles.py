import logging
from api.dependencies import get_supabase
from api.config import get_settings

log = logging.getLogger(__name__)


def get_active_profile() -> dict:
    sb = get_supabase()
    try:
        res = sb.table("settings").select("value").eq("key", "active_profile").maybe_single().execute()
        if res and res.data:
            return res.data["value"]
    except Exception:
        pass

    settings = get_settings()
    return {
        "name": "default",
        "wallet_address": "",
        "polymarket_api_key": settings.polymarket_api_key,
        "polymarket_secret": settings.polymarket_secret,
        "polymarket_passphrase": settings.polymarket_passphrase,
        "polymarket_private_key": settings.polymarket_private_key,
        "multi_exec": False,
    }


def list_profiles() -> list[dict]:
    sb = get_supabase()
    try:
        res = sb.table("settings").select("value").eq("key", "profiles").maybe_single().execute()
        if res and res.data:
            return res.data["value"].get("profiles", [])
    except Exception:
        pass
    return [get_active_profile()]


def save_profile(profile: dict):
    sb = get_supabase()
    profiles = list_profiles()

    if "multi_exec" not in profile:
        profile["multi_exec"] = False

    existing_idx = next((i for i, p in enumerate(profiles) if p["name"] == profile["name"]), None)
    if existing_idx is not None:
        profiles[existing_idx] = profile
    else:
        profiles.append(profile)

    sb.table("settings").upsert({"key": "profiles", "value": {"profiles": profiles}}).execute()


def switch_profile(profile_name: str) -> dict:
    profiles = list_profiles()
    profile = next((p for p in profiles if p["name"] == profile_name), None)
    if not profile:
        raise ValueError(f"Profile '{profile_name}' not found")

    sb = get_supabase()
    sb.table("settings").upsert({"key": "active_profile", "value": profile}).execute()

    sb.table("audit_log").insert({
        "action": "profile_switch",
        "actor": "user",
        "resource_type": "profile",
        "resource_id": profile_name,
        "details": {"wallet": profile.get("wallet_address", "")},
    }).execute()

    log.info(f"Switched to profile: {profile_name}")
    return profile


def delete_profile(profile_name: str):
    if profile_name == "default":
        raise ValueError("Cannot delete default profile")

    sb = get_supabase()
    profiles = list_profiles()
    profiles = [p for p in profiles if p["name"] != profile_name]
    sb.table("settings").upsert({"key": "profiles", "value": {"profiles": profiles}}).execute()


def set_multi_exec(profile_name: str, enabled: bool) -> dict:
    profiles = list_profiles()
    profile = next((p for p in profiles if p["name"] == profile_name), None)
    if not profile:
        raise ValueError(f"Profile '{profile_name}' not found")

    profile["multi_exec"] = enabled
    save_profile(profile)

    sb = get_supabase()
    sb.table("audit_log").insert({
        "action": "multi_exec_toggle",
        "actor": "user",
        "resource_type": "profile",
        "resource_id": profile_name,
        "details": {"multi_exec": enabled},
    }).execute()

    log.info(f"Profile '{profile_name}' multi_exec={'ON' if enabled else 'OFF'}")
    return profile


def get_multi_exec_profiles() -> list[dict]:
    profiles = list_profiles()
    return [p for p in profiles if p.get("multi_exec", False)]
