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
        "inactive": ":no_entry:",
        "active": ":white_check_mark:",
        "paper": ":memo:",
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
    # "handle='all'" is the sentinel meaning "engine cycle is stalled" (the
    # decision-log freshness probe). Make the message readable in both cases.
    if handle == "all":
        msg = (
            f":warning: *Engine cycle stalled — no {source} updates in {hours:.1f}h*\n"
            f"Bot will skip new entries until the next successful cycle. "
            f"Check Railway deploy logs for module evaluation errors."
        )
    else:
        msg = (
            f":warning: *Stale Data — {source}*\n"
            f"Handle *{handle}* has not updated in *{hours:.1f}h*. "
            f"Bot will skip new entries until data refreshes."
        )
    await send_slack(msg)


async def notify_daily_module_status_digest():
    """Daily Slack heartbeat — fires every morning/evening even when all
    modules are healthy. The user explicitly wants 'alert when bot is dead
    (daily)', and the only reliable way to know the bot is dead is for
    the heartbeat to STOP arriving. Silent days hide failure modes
    (Slack creds expired, Railway service down, scheduler stuck) so we
    always send.

    Format on a healthy day:
      :white_check_mark: *Daily Bot Heartbeat*
      All 3 modules running: Spike Trading (active), Trump (paper), Elon (paper).

    Format on a degraded day:
      :bell: *Daily Bot Heartbeat — 1 module not active*
      :white_check_mark: Spike Trading (active)
      :no_entry: Trump (inactive: circuit_breaker)
        _Auto-paused after 5 consecutive losses_
      :white_check_mark: Elon (paper)

    Reason source for inactive modules: most recent log entry where
    log_type IN ('system','risk'). Falls back to inactive_detail or
    inactive_reason when no log exists.
    """
    # Has its own toggle (alert_daily_module_digest_enabled). Defaults ON.
    cfg = _alert_settings()
    if cfg.get("alert_daily_module_digest_enabled", True) is False:
        return
    if not _is_alert_enabled("module_status_change"):
        return
    # Bucket the dedupe key by the calling hour-block so 9 AM ET and
    # 5 PM ET fire independently. Without this the 5pm digest would be
    # silenced by the morning's 24h dedupe.
    from datetime import datetime as _dt, timezone as _tz
    hour_utc = _dt.now(_tz.utc).hour
    bucket = "morning" if hour_utc < 18 else "evening"
    key = f"alert_daily_module_digest_{bucket}"
    if not _dedupe_check_and_record(key, 23.0, {}):
        return
    try:
        sb = get_supabase()
        mods = sb.table("modules").select("id,name,status,inactive_reason,inactive_detail").execute().data or []
        if not mods:
            await send_slack(":bell: *Daily Bot Heartbeat* — no modules configured.")
            return

        lines = []
        n_down = 0
        for m in mods:
            status = (m.get("status") or "").lower()
            name = m.get("name") or m.get("id")
            if status == "active":
                lines.append(f":white_check_mark: *{name}* — `active` (real money)")
            elif status == "paper":
                lines.append(f":blue_book: *{name}* — `paper` (paper trades)")
            else:
                n_down += 1
                reason_label = m.get("inactive_reason") or "unknown"
                detail = m.get("inactive_detail")
                line = f":no_entry: *{name}* — `inactive ({reason_label})`"
                if detail:
                    line += f"\n_{detail[:200]}_"
                else:
                    # Fall back to most recent system/risk log entry
                    try:
                        logs = sb.table("logs").select("message,created_at") \
                            .eq("module_id", m["id"]).in_("log_type", ["system", "risk"]) \
                            .order("created_at", desc=True).limit(1).execute().data or []
                        if logs:
                            line += f"\n_{(logs[0].get('message') or '')[:200]}_"
                    except Exception:
                        pass
                lines.append(line)

        if n_down == 0:
            header = f":white_check_mark: *Daily Bot Heartbeat — all {len(mods)} modules running*"
        else:
            header = f":bell: *Daily Bot Heartbeat — {n_down}/{len(mods)} not active*"

        await send_slack(header + "\n\n" + "\n\n".join(lines))
    except Exception as e:
        log.warning(f"daily module digest failed: {e}")


async def notify_rejection_spike(
    module_id: str, module_name: str, count: int, top_reasons: list[str],
    recent: list[dict] | None = None,
):
    """N risk-rejected signals back-to-back. Often means a config is misaligned
    with current market conditions (e.g. min_edge_threshold too high).

    `recent` is a list of rejection records (module_name, market_id, bracket,
    event_slug, reason). When provided, the message lists each distinct
    auction with a Polymarket link so the user can click straight to the
    market that's being blocked."""
    if not _is_alert_enabled("rejection_spike"):
        return
    key = f"alert_rejection_spike:{module_id}"
    if not _dedupe_check_and_record(key, _cooldown_hours("rejection_spike"),
                                    {"count": count}):
        return
    reasons_str = "\n".join(f"• {r}" for r in top_reasons[:3])

    # Distinct (slug, bracket) pairs from the recent window, preserving
    # most-recent-first order. Cap at 5 lines so Slack doesn't get spammed.
    auction_lines: list[str] = []
    if recent:
        seen: set[tuple[str, str]] = set()
        for r in reversed(recent):
            slug = (r.get("event_slug") or "").strip()
            bracket = (r.get("bracket") or "").strip()
            ident = (slug, bracket)
            if not slug or ident in seen:
                continue
            seen.add(ident)
            label = f"`{bracket}`" if bracket else "auction"
            auction_lines.append(f"• <https://polymarket.com/event/{slug}|{label} — {slug}>")
            if len(auction_lines) >= 5:
                break

    msg = (
        f":information_source: *Rejection Spike — module: {module_name}*\n"
        f"*{count}* signals rejected back-to-back. Top reasons:\n{reasons_str}"
    )
    if auction_lines:
        msg += "\n*Auctions blocked:*\n" + "\n".join(auction_lines)
    msg += "\n_Often means a config knob (edge threshold, exposure cap) is misaligned._"
    await send_slack(msg)
