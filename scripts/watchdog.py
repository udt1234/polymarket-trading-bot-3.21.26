"""Autonomous module watchdog / self-heal. Scheduled by a systemd timer on the
Dublin box (every 15 min). Ensures the engine is cycling and every expected
module is running; auto-fixes what it can and logs the result to Supabase (so
the dashboard shows what it did).

Targets the failure systemd CANNOT see: the engine SCHEDULER stalls while the
process stays up (the cycle stops firing). We detect a stale last_cycle and
restart the service to revive the scheduler. (Process death is already handled
by the service's restart policy.) NEVER call /api/engine/stop - that is a kill
switch that closes positions; process-level `systemctl restart` is the safe fix.
"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from api.dependencies import get_supabase  # noqa: E402

STALE_MIN = 15         # an engine cycle older than this = the scheduler stalled
RESTART_COOLDOWN_MIN = 8  # don't restart again within this window of a prior watchdog restart
STARVE_HOURS = 6       # signals arriving but ZERO approved for this long = a gate is eating everything
NO_ORDER_HOURS = 24    # no order placed by any paper/active module this long = bench is dead


def _last_cycle_age_min() -> float | None:
    """Minutes since the last engine cycle, or None if unreachable/never."""
    try:
        r = httpx.get("http://localhost:8000/api/engine/health", timeout=10)
        lc = (r.json() or {}).get("last_cycle_at")
    except Exception:
        return None
    if not lc:
        return None
    try:
        dt = datetime.fromisoformat(lc.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0


def _signal_approval_stats(sb, hours: int) -> tuple[int, int]:
    """(signals, approved) in the last `hours` from the signals table."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = (sb.table("signals").select("approved")
            .gte("created_at", since).limit(20000).execute().data) or []
    return len(rows), sum(1 for r in rows if r.get("approved"))


def _dominant_rejections(sb, hours: int, top: int = 4) -> str:
    """Human-readable breakdown of WHY signals were rejected in the window, so a
    starvation alert names the actual gate instead of 'a gate is eating everything'.
    Returns e.g. 'stake_below_floor x32, module_budget_cap_500 x28, duplicate x9'."""
    from collections import Counter
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = (sb.table("signals").select("rejection_reason")
            .eq("approved", False).gte("created_at", since).limit(20000).execute().data) or []
    if not rows:
        return "(no rejections logged)"
    c = Counter((r.get("rejection_reason") or "unknown") for r in rows)
    return ", ".join(f"{reason} x{n}" for reason, n in c.most_common(top))


def _hours_since_last_order(sb) -> float | None:
    """Hours since ANY order was placed, or None if never/unreadable."""
    r = (sb.table("orders").select("created_at")
         .order("created_at", desc=True).limit(1).execute().data) or []
    if not r:
        return None
    try:
        dt = datetime.fromisoformat(r[0]["created_at"].replace("Z", "+00:00"))
    except (ValueError, KeyError):
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _recent_watchdog_restart(sb, within_min: int) -> bool:
    """True if this watchdog logged a service restart within the last `within_min`
    minutes (its own restart actions are logged to Supabase with 'systemctl restart'
    in the message). Prevents restart-looping while a fresh boot is still warming up."""
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=within_min)).isoformat()
        rows = (sb.table("logs").select("id")
                .eq("log_type", "system").gte("created_at", since)
                .like("message", "%systemctl restart polybot%")
                .limit(1).execute().data) or []
        return bool(rows)
    except Exception:
        return False  # fail toward allowing the restart (availability over churn-guard)


DIGEST_HOUR_UTC = int(os.getenv("WATCHDOG_DIGEST_HOUR_UTC", "13"))  # ~9am ET


def _daily_digest(sb) -> str:
    """A once-a-day heartbeat so silence can NEVER be mistaken for 'fine' - the
    user gets the bot's real numbers every morning without having to ask."""
    now = datetime.now(timezone.utc)
    age = _last_cycle_age_min()
    eng = "cycling" if (age is not None and age <= STALE_MIN) else f"STALE ({age}m)"
    sigs, appr = _signal_approval_stats(sb, 24)
    since24 = (now - timedelta(hours=24)).isoformat()
    fills = len((sb.table("orders").select("id").eq("status", "filled")
                 .gte("created_at", since24).limit(20000).execute().data) or [])
    pos = (sb.table("positions").select("realized_pnl,status,closed_at,size,avg_price")
           .limit(20000).execute().data) or []
    today = now.date().isoformat()
    d7 = now - timedelta(days=7)
    r_today = sum(float(p.get("realized_pnl") or 0) for p in pos
                  if (p.get("closed_at") or "")[:10] == today)
    r_7d = sum(float(p.get("realized_pnl") or 0) for p in pos if p.get("closed_at")
               and datetime.fromisoformat(p["closed_at"].replace("Z", "+00:00")) >= d7)
    open_pos = [p for p in pos if p.get("status") == "open"]
    open_notional = sum(float(p.get("size") or 0) * float(p.get("avg_price") or 0) for p in open_pos)
    mods = (sb.table("modules").select("name").neq("status", "inactive").execute().data) or []
    why = _dominant_rejections(sb, 24) if (sigs > 0 and appr == 0) else ""
    lines = [
        "📊 Polybot daily digest",
        f"Engine: {eng}",
        f"Signals 24h: {sigs} | approved: {appr}" + (f"\n  gates: {why}" if why else ""),
        f"Paper fills 24h: {fills}",
        f"Realized P&L: today ${r_today:+.2f} | 7d ${r_7d:+.2f}",
        f"Open: {len(open_pos)} positions | ${open_notional:.0f} notional",
        f"Active modules ({len(mods)}): " + (", ".join(sorted(m["name"] for m in mods)) or "none"),
    ]
    return "\n".join(lines)


def _maybe_send_daily_digest(sb) -> None:
    now = datetime.now(timezone.utc)
    if now.hour < DIGEST_HOUR_UTC:
        return
    today = now.date().isoformat()
    try:
        rows = (sb.table("settings").select("value").eq("key", "watchdog_digest")
                .limit(1).execute().data) or []
        if rows and (rows[0].get("value") or {}).get("last_date") == today:
            return  # already sent today
    except Exception:
        pass
    try:
        from api.services.notifications import notify
        notify(_daily_digest(sb))
        sb.table("settings").upsert({"key": "watchdog_digest",
                                     "value": {"last_date": today}}).execute()
    except Exception as e:
        print(f"[watchdog] digest failed: {e}", flush=True)


def main() -> None:
    sb = get_supabase()
    actions: list[str] = []
    alerts: list[str] = []  # things it CANNOT auto-fix but MUST surface (no silent "healthy")

    # 1. Engine cycling? Restart the service if the scheduler stalled (or the
    #    API is unreachable / has never cycled). COOLDOWN: a fresh restart takes up
    #    to one cycle interval (300s) to log its first last_cycle_at, so if WE
    #    restarted within RESTART_COOLDOWN_MIN, skip - restarting again would reset
    #    the first-cycle timer and cause a restart loop (qa-bug-hunter, 2026-07-22).
    age = _last_cycle_age_min()
    if age is None or age > STALE_MIN:
        if _recent_watchdog_restart(sb, RESTART_COOLDOWN_MIN):
            alerts.append(f"engine not cycling (age={age}m) but a watchdog restart "
                          f"fired <{RESTART_COOLDOWN_MIN}m ago - waiting for it to settle")
        else:
            actions.append(f"engine not cycling (age={age}m) -> systemctl restart polybot.service")
            subprocess.run(["sudo", "systemctl", "restart", "polybot.service"], check=False)

    # 1b. THE BLIND SPOT that hid a 6-day stall: engine healthy + signals flowing
    #     but a gate rejecting 100% of them. Detect signals>0 & approved==0, and
    #     a total order drought. Cannot auto-fix (it's a config/logic call), so
    #     ALERT loudly instead of reporting "healthy".
    try:
        sigs, approved = _signal_approval_stats(sb, STARVE_HOURS)
        if sigs > 0 and approved == 0:
            why = _dominant_rejections(sb, STARVE_HOURS)
            alerts.append(f"SIGNAL STARVATION: {sigs} signals in {STARVE_HOURS}h, "
                          f"0 approved. Top gates: {why}")
    except Exception as e:
        alerts.append(f"signal-stats check failed: {type(e).__name__}")
    try:
        oh = _hours_since_last_order(sb)
        if oh is None or oh > NO_ORDER_HOURS:
            alerts.append(f"ORDER DROUGHT: no order placed in "
                          f"{'ever' if oh is None else f'{oh:.0f}h'} - bench is not trading")
    except Exception as e:
        alerts.append(f"order-drought check failed: {type(e).__name__}")

    # 2. Any expected module wrongly paused? Re-activate to PAPER (safe - never
    #    to 'active'). Skip intentionally decommissioned modules.
    rows = (sb.table("modules").select("id,name,status,inactive_reason")
            .eq("status", "inactive").execute().data) or []
    for m in rows:
        # Never resurrect a module that was paused ON PURPOSE: decommissioned, or
        # paused because its THESIS is dead on this market (2026-07-23). Auto-
        # reviving a known-losing strategy is worse than leaving it off.
        if (m.get("inactive_reason") or "").lower() in ("decommissioned", "dead_thesis"):
            continue
        sb.table("modules").update({"status": "paper", "inactive_reason": None}) \
            .eq("id", m["id"]).execute()
        actions.append(f"re-activated '{m['name']}' -> paper (was inactive: {m.get('inactive_reason')})")

    if actions and alerts:
        msg = "watchdog fixed: " + "; ".join(actions) + " | ALERTS: " + "; ".join(alerts)
        sev = "error"
    elif alerts:
        msg = "watchdog ALERTS (needs a human): " + "; ".join(alerts)
        sev = "error"
    elif actions:
        msg = "watchdog fixed: " + "; ".join(actions)
        sev = "warning"
    else:
        msg = "watchdog: all healthy"
        sev = "info"
    try:
        sb.table("logs").insert({
            "log_type": "system", "severity": sev,
            "message": msg,
            "metadata": {"actions": actions, "alerts": alerts, "engine_age_min": age},
        }).execute()
    except Exception:
        pass
    # Telegram ping when we FIXED something OR when there's an unfixable ALERT
    # (silence must never again mean "assumed fine").
    if actions or alerts:
        try:
            from api.services.notifications import notify
            parts = []
            if actions:
                parts.append("🐕 Polybot watchdog fixed:\n- " + "\n- ".join(actions))
            if alerts:
                parts.append("🚨 Polybot watchdog ALERT (needs you):\n- " + "\n- ".join(alerts))
            notify("\n\n".join(parts))
        except Exception:
            pass

    # Guaranteed once-a-day heartbeat (independent of alerts): the user should
    # never again "realize nothing is running" - a digest lands every morning.
    _maybe_send_daily_digest(sb)
    print(msg)


if __name__ == "__main__":
    main()
