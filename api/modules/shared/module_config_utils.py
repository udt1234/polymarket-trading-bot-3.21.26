"""Shared helpers for module_config.py files.

Lives in shared/ so multiple modules can use these without importing from
each other. Original was in truth_social/module_config.py and Elon was
importing from there — direct cross-module dependency.
"""
from datetime import datetime, timedelta, timezone


def normalize_regime_override(merged: dict) -> dict:
    """Server-side guard: when an override regime is set, ensure default_hours
    is sane (1-720) and recompute expires_at if it's missing, in the past, or
    clearly bogus. Without this guard, a dashboard payload that sent 0/empty
    hours produced expires_at = now, which the bot then auto-cleared on the
    very next cycle — making the override look like it "didn't take"."""
    override = (merged.get("manual_regime_override") or "").strip().upper()
    if not override:
        merged["manual_regime_override"] = ""
        merged["manual_regime_override_expires_at"] = ""
        return merged
    raw_hours = merged.get("manual_regime_override_default_hours")
    try:
        hours = float(raw_hours) if raw_hours is not None else 1.0
    except (TypeError, ValueError):
        hours = 1.0
    if hours < 1:
        hours = 1.0
    if hours > 720:
        hours = 720.0
    merged["manual_regime_override_default_hours"] = hours
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
