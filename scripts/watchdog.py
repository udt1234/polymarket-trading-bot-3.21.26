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
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from api.dependencies import get_supabase  # noqa: E402

STALE_MIN = 15  # an engine cycle older than this = the scheduler stalled


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


def main() -> None:
    sb = get_supabase()
    actions: list[str] = []

    # 1. Engine cycling? Restart the service if the scheduler stalled (or the
    #    API is unreachable / has never cycled).
    age = _last_cycle_age_min()
    if age is None or age > STALE_MIN:
        actions.append(f"engine not cycling (age={age}m) -> systemctl restart polybot.service")
        subprocess.run(["sudo", "systemctl", "restart", "polybot.service"], check=False)

    # 2. Any expected module wrongly paused? Re-activate to PAPER (safe - never
    #    to 'active'). Skip intentionally decommissioned modules.
    rows = (sb.table("modules").select("id,name,status,inactive_reason")
            .eq("status", "inactive").execute().data) or []
    for m in rows:
        if (m.get("inactive_reason") or "").lower() == "decommissioned":
            continue
        sb.table("modules").update({"status": "paper", "inactive_reason": None}) \
            .eq("id", m["id"]).execute()
        actions.append(f"re-activated '{m['name']}' -> paper (was inactive: {m.get('inactive_reason')})")

    msg = "watchdog: all healthy" if not actions else "watchdog fixed: " + "; ".join(actions)
    try:
        sb.table("logs").insert({
            "log_type": "system", "severity": "warning" if actions else "info",
            "message": msg, "metadata": {"actions": actions, "engine_age_min": age},
        }).execute()
    except Exception:
        pass
    print(msg)


if __name__ == "__main__":
    main()
