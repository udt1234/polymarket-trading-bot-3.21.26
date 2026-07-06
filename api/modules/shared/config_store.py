"""Per-module config storage (BUILD_SPEC F1). Key `module_config:{module_id}`
in the settings table. Reads fall back to the module's DEFAULT_CONFIG when
no row exists; writes MERGE incoming fields into the stored config, never
overwrite the whole dict."""
import logging

from api.dependencies import get_supabase

log = logging.getLogger(__name__)


def get_module_config(module_id: str, defaults: dict) -> dict:
    merged = dict(defaults)
    try:
        res = (get_supabase().table("settings").select("value")
               .eq("key", f"module_config:{module_id}").limit(1).execute())
        if res.data:
            merged.update(res.data[0].get("value") or {})
    except Exception:
        log.exception("config read failed for %s - using defaults", module_id)
    return merged


def save_module_config(module_id: str, patch: dict, defaults: dict) -> dict:
    merged = get_module_config(module_id, defaults)
    merged.update(patch or {})
    get_supabase().table("settings").upsert({
        "key": f"module_config:{module_id}", "value": merged,
    }).execute()
    return merged
