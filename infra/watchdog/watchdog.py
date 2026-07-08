"""External stuck/stale watchdog (BUILD_SPEC I4, task 2026-07-08).

Runs on a SEPARATE host from the trading bot (Railway), so if the whole
Dublin bot dies this still fires. Polls Supabase every WATCHDOG_INTERVAL_SEC
and alerts Telegram on:
  - ENGINE STALE  : no cycle log within WATCHDOG_STALE_MIN minutes
  - MODULE DOWN   : a module flipped to inactive (kill_switch/error/data_stale)
  - BREAKER TRIP  : circuit_breaker.cooldown_until in the future
  - ERROR SPIKE   : > WATCHDOG_ERR_MAX error/critical logs in the last window

Edge-triggered with recovery: alerts once when a condition turns bad, again
only after WATCHDOG_REALERT_MIN if still bad, and sends a RECOVERED message
when it clears. De-dup state lives in the Supabase settings row
`watchdog_state` so restarts don't re-spam.

Pure httpx (Supabase REST + Telegram REST) - no heavy deps.
"""
import json
import os
import time
from datetime import datetime, timezone

import httpx

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]

STALE_MIN = float(os.getenv("WATCHDOG_STALE_MIN", "15"))
ERR_MAX = int(os.getenv("WATCHDOG_ERR_MAX", "10"))
ERR_WINDOW_MIN = float(os.getenv("WATCHDOG_ERR_WINDOW_MIN", "15"))
REALERT_MIN = float(os.getenv("WATCHDOG_REALERT_MIN", "60"))
INTERVAL_SEC = int(os.getenv("WATCHDOG_INTERVAL_SEC", "600"))

_H = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sb_get(path: str, params: dict) -> list:
    r = httpx.get(f"{SB_URL}/rest/v1/{path}", headers=_H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _iso_ago(minutes: float) -> str:
    return (_now().timestamp() - minutes * 60).__str__()


def telegram(text: str) -> None:
    try:
        httpx.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                   json={"chat_id": TG_CHAT, "text": text,
                         "disable_web_page_preview": True}, timeout=20)
    except Exception as e:
        print(f"[watchdog] telegram send failed: {e}", flush=True)


def load_state() -> dict:
    rows = _sb_get("settings", {"key": "eq.watchdog_state", "select": "value", "limit": "1"})
    return (rows[0].get("value") if rows else {}) or {}


def save_state(state: dict) -> None:
    httpx.post(f"{SB_URL}/rest/v1/settings",
               headers={**_H, "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates"},
               json={"key": "watchdog_state", "value": state}, timeout=30)


def check() -> dict:
    """Return {condition_key: message or None}. None = healthy."""
    out: dict[str, str | None] = {}

    # 1. Engine stale
    cyc = _sb_get("logs", {
        "log_type": "eq.system", "message": "like.Cycle:*",
        "select": "created_at", "order": "created_at.desc", "limit": "1"})
    if not cyc:
        out["engine"] = "🔴 ENGINE: no cycle logs at all"
    else:
        age = (_now() - datetime.fromisoformat(
            cyc[0]["created_at"].replace("Z", "+00:00"))).total_seconds() / 60
        out["engine"] = (f"🔴 ENGINE STALE: no cycle for {age:.0f} min "
                         f"(threshold {STALE_MIN:.0f}m)") if age > STALE_MIN else None

    # 2. Modules down
    dead = _sb_get("modules", {
        "status": "eq.inactive", "select": "name,inactive_reason",
        "inactive_reason": "in.(kill_switch,error,data_stale,circuit_breaker)"})
    out["modules"] = ("🔴 MODULE DOWN: " + ", ".join(
        f"{m['name']} ({m.get('inactive_reason')})" for m in dead)) if dead else None

    # 3. Circuit breaker
    br = _sb_get("settings", {"key": "eq.circuit_breaker", "select": "value", "limit": "1"})
    cd = (br[0]["value"].get("cooldown_until") if br else "") or ""
    out["breaker"] = (f"🛑 CIRCUIT BREAKER tripped, paused until {cd}"
                      if cd and cd > _now().isoformat() else None)

    # 4. Error spike
    since = (_now().timestamp() - ERR_WINDOW_MIN * 60)
    since_iso = datetime.fromtimestamp(since, timezone.utc).isoformat()
    errs = _sb_get("logs", {
        "severity": "in.(error,critical)", "created_at": f"gte.{since_iso}",
        "select": "id"})
    out["errors"] = (f"🔴 ERROR SPIKE: {len(errs)} error/critical logs in "
                     f"{ERR_WINDOW_MIN:.0f}m (threshold {ERR_MAX})"
                     ) if len(errs) > ERR_MAX else None
    return out


def run_once() -> None:
    try:
        conditions = check()
    except Exception as e:
        print(f"[watchdog] check failed: {e}", flush=True)
        return
    state = load_state()
    now_iso = _now().isoformat()
    changed = False
    for key, msg in conditions.items():
        prev = state.get(key) or {}
        was_bad = bool(prev.get("bad"))
        if msg:  # currently bad
            last = prev.get("last_alert_at") or ""
            due = (not was_bad) or (
                last and (_now() - datetime.fromisoformat(last)).total_seconds() / 60 >= REALERT_MIN)
            if due:
                telegram(f"{msg}\n\nBot: polybot (Dublin) · {now_iso}")
                state[key] = {"bad": True, "last_alert_at": now_iso}
                changed = True
        elif was_bad:  # recovered
            telegram(f"✅ RECOVERED: {key} is healthy again · {now_iso}")
            state[key] = {"bad": False}
            changed = True
    if changed:
        save_state(state)
    bad = [k for k, v in conditions.items() if v]
    print(f"[watchdog] {now_iso} checked; bad={bad or 'none'}", flush=True)


def main() -> None:
    print(f"[watchdog] starting; interval={INTERVAL_SEC}s stale={STALE_MIN}m", flush=True)
    telegram("🐕 Watchdog online - monitoring polybot for stale/stuck/breaker/errors.")
    while True:
        run_once()
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
