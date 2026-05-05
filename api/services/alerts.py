"""Operational alerts for the bot.

Five distinct alert types, each individually toggleable from settings.notifications:
  1. bot_paused              — engine globally paused / circuit breaker / kill switch
  2. module_status_change    — a module flipped active <-> paused/killed
  3. repeated_errors         — same error signature 3+ times in 15 min
  4. stale_data              — xTracker fetch hasn't updated in N hours
  5. rejection_spike         — N risk-rejected signals back-to-back

Each notify_* function does its own dedupe via the settings table to prevent
alert storms (cooldown configurable per-alert).
"""
import logging
import time
from typing import Any

from api.dependencies import get_supabase
from api.services.notifications import send_slack

log = logging.getLogger(__name__)

# Default cooldowns per alert type (hours). Settings can override.
DEFAULT_COOLDOWNS = {
    "bot_paused": 1.0,
    "module_status_change": 1.0,
    "repeated_errors": 0.5,    # 30 min — these can persist for a while
    "stale_data": 2.0,
    "rejection_spike": 0.25,   # 15 min — actionable signal worth seeing more often
}


def _alert_settings() -> dict:
    try:
        sb = get_supabase()
        res = sb.table("settings").select("value").eq("key", "notifications").execute()
        return (res.data[0].get("value") or {}) if res.data else {}
    except Exception:
        return {}


def _is_alert_enabled(alert_type: str) -> bool:
    """Each alert type has its own toggle in settings, falling back to True."""
    cfg = _alert_settings()
    # Master kill switches first
    if not cfg.get("slack_enabled", True):
        return False
    if not cfg.get("enabled", True):
        return False
    # Per-alert toggle (default ON)
    return cfg.get(f"alert_{alert_type}_enabled", True) is not False


def _cooldown_hours(alert_type: str) -> float:
    cfg = _alert_settings()
    val = cfg.get(f"alert_{alert_type}_cooldown_hours")
    return float(val) if val is not None else DEFAULT_COOLDOWNS.get(alert_type, 1.0)


def _dedupe_check_and_record(key: str, cooldown_hours: float, payload: dict[str, Any]) -> bool:
    """Returns True if we should fire (not in cooldown). Records the fire on True."""
    try:
        sb = get_supabase()
        row = sb.table("settings").select("value").eq("key", key).execute()
        if row.data:
            last_ts = float((row.data[0].get("value") or {}).get("ts", 0))
            elapsed_hours = (time.time() - last_ts) / 3600.0
            if elapsed_hours < cooldown_hours:
                return False
        sb.table("settings").upsert({
            "key": key,
            "value": {**payload, "ts": time.time()},
        }).execute()
        return True
    except Exception as e:
        log.warning(f"alert dedupe check failed for {key}: {e}")
        # Fail-open: if we can't dedupe, send anyway. Better noisy than silent.
        return True


async def notify_bot_paused(reason: str, scope: str = "engine", details: dict | None = None):
    """Engine globally paused or circuit breaker tripped or manual kill."""
    if not _is_alert_enabled("bot_paused"):
        return
    key = f"alert_bot_paused:{scope}"
    if not _dedupe_check_and_record(key, _cooldown_hours("bot_paused"), {"reason": reason}):
        return
    detail_str = ""
    if details:
        detail_str = "\n" + "\n".join(f"• {k}: {v}" for k, v in details.items())
    msg = (
        f":octagonal_sign: *Bot Paused — {scope}*\n"
        f"*Reason:* {reason}{detail_str}\n"
        f"_Bot will not place new trades until resumed. Exits still fire._"
    )
    await send_slack(msg)


async def notify_module_status_change(
    module_id: str, name: str, old_status: str, new_status: str, reason: str = "",
):
    """A module went from one status to another (active <-> paused/killed)."""
    if not _is_alert_enabled("module_status_change"):
        return
    key = f"alert_module_status:{module_id}:{new_status}"
    if not _dedupe_check_and_record(key, _cooldown_hours("module_status_change"),
                                    {"old": old_status, "new": new_status}):
        return
    emoji = {
        "killed": ":skull:",
        "paused": ":pause_button:",
        "active": ":white_check_mark:",
    }.get(new_status, ":information_source:")
    msg = f"{emoji} *Module status: {name}*\n*{old_status}* -> *{new_status}*"
    if reason:
        msg += f"\n_Reason: {reason}_"
    await send_slack(msg)


async def notify_repeated_errors(
    error_signature: str, count: int, time_window_minutes: float, sample: str = "",
):
    """Same error signature has fired N+ times in a window."""
    if not _is_alert_enabled("repeated_errors"):
        return
    key = f"alert_repeated_errors:{error_signature[:80]}"
    if not _dedupe_check_and_record(key, _cooldown_hours("repeated_errors"),
                                    {"signature": error_signature[:120], "count": count}):
        return
    msg = (
        f":warning: *Repeated Error*\n"
        f"`{error_signature[:120]}` — *{count}* occurrences in {time_window_minutes:.0f} min"
    )
    if sample:
        msg += f"\n_Latest: {sample[:200]}_"
    await send_slack(msg)


async def notify_stale_data(handle: str, hours: float, source: str = "xTracker"):
    """Data source hasn't updated in too long."""
    if not _is_alert_enabled("stale_data"):
        return
    key = f"alert_stale_data:{handle}:{source}"
    if not _dedupe_check_and_record(key, _cooldown_hours("stale_data"),
                                    {"hours": hours}):
        return
    msg = (
        f":warning: *Stale Data — {source}*\n"
        f"Handle *{handle}* has not updated in *{hours:.1f}h*. "
        f"Bot will skip new entries until data refreshes."
    )
    await send_slack(msg)


async def notify_daily_module_status_digest():
    """Daily Slack message listing every module that is NOT active, with the
    most recent reason. Fires at most once per day (24h dedupe). Skipped
    entirely if zero modules are down (all-clear days are silent).

    Reason source: most recent log entry for the module where log_type IN
    ('system','risk') with a non-empty message in the last 7 days. Falls back
    to 'No recent reason logged' if nothing found.
    """
    # Has its own toggle (alert_daily_module_digest_enabled). Defaults ON, but
    # if explicitly disabled, fall back to the module_status_change toggle so
    # turning that off silences both.
    cfg = _alert_settings()
    if cfg.get("alert_daily_module_digest_enabled", True) is False:
        return
    if not _is_alert_enabled("module_status_change"):
        return
    key = "alert_daily_module_digest"
    if not _dedupe_check_and_record(key, 24.0, {}):
        return
    try:
        sb = get_supabase()
        # All non-active modules (paused, killed, scaffold, paper)
        mods = sb.table("modules").select("id,name,status").execute().data or []
        # 'active' AND 'paper' are healthy operational states — only flag
        # truly degraded modules (paused/killed/scaffold).
        down = [m for m in mods if (m.get("status") or "").lower() not in ("active", "paper")]
        if not down:
            return  # Silence on all-clear days

        lines = []
        for m in down:
            mid = m["id"]
            reason = "No recent reason logged."
            try:
                logs = sb.table("logs").select("message,log_type,severity,created_at") \
                    .eq("module_id", mid).in_("log_type", ["system", "risk"]) \
                    .order("created_at", desc=True).limit(1).execute().data or []
                if logs:
                    reason = (logs[0].get("message") or reason)[:240]
            except Exception:
                pass
            emoji = {
                "killed": ":skull:",
                "paused": ":pause_button:",
                "paper":  ":page_facing_up:",
                "scaffold": ":construction:",
            }.get((m.get("status") or "").lower(), ":grey_question:")
            lines.append(f"{emoji} *{m.get('name')}* — `{m.get('status')}`\n_{reason}_")

        msg = (
            f":bell: *Daily Module Status — {len(down)} not active*\n\n"
            + "\n\n".join(lines)
        )
        await send_slack(msg)
    except Exception as e:
        log.warning(f"daily module digest failed: {e}")


async def notify_rejection_spike(
    module_id: str, module_name: str, count: int, top_reasons: list[str],
):
    """N risk-rejected signals back-to-back. Often means a config is misaligned
    with current market conditions (e.g. min_edge_threshold too high)."""
    if not _is_alert_enabled("rejection_spike"):
        return
    key = f"alert_rejection_spike:{module_id}"
    if not _dedupe_check_and_record(key, _cooldown_hours("rejection_spike"),
                                    {"count": count}):
        return
    reasons_str = "\n".join(f"• {r}" for r in top_reasons[:3])
    msg = (
        f":information_source: *Rejection Spike — {module_name}*\n"
        f"*{count}* signals rejected back-to-back. Top reasons:\n{reasons_str}\n"
        f"_Often means a config knob (edge threshold, exposure cap) is misaligned._"
    )
    await send_slack(msg)
