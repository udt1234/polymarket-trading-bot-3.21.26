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

All human-facing timestamps in Eastern (America/New_York) via zoneinfo.
Breaker alerts include the losing-streak breakdown so Sir sees exactly which
trades tripped it.

Pure httpx (Supabase REST + Telegram REST) - no heavy deps.
"""
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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

ET = ZoneInfo("America/New_York")
_H = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _et(dt: datetime | str | None) -> str:
    """Format any datetime (or ISO string) as '2026-07-24 12:22 ET'."""
    if dt is None or dt == "":
        return "-"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).strftime("%Y-%m-%d %I:%M %p ET").replace(" 0", " ")


def _sb_get(path: str, params: dict) -> list:
    r = httpx.get(f"{SB_URL}/rest/v1/{path}", headers=_H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def telegram(text: str) -> None:
    try:
        httpx.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                   json={"chat_id": TG_CHAT, "text": text,
                         "parse_mode": "HTML",
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


def _fetch_losing_streak(max_lookback: int = 20) -> list[dict]:
    """Return the LOSING trades that make up the current consecutive-loss streak
    (walking closed positions newest-first, stopping at the first WIN)."""
    rows = _sb_get("positions", {
        "status": "eq.closed",
        "select": "id,module_id,market_id,bracket,avg_price,exit_price,realized_pnl,closed_at",
        "order": "closed_at.desc",
        "limit": str(max_lookback),
    })
    losses: list[dict] = []
    for r in rows:
        pnl = float(r.get("realized_pnl") or 0)
        if pnl >= 0:
            break  # streak ends at first win (walking backwards)
        losses.append(r)
    if not losses:
        return []
    # Enrich with module names in one round-trip
    mod_ids = list({r["module_id"] for r in losses if r.get("module_id")})
    name_map: dict[str, str] = {}
    if mod_ids:
        mrows = _sb_get("modules", {
            "id": f"in.({','.join(mod_ids)})",
            "select": "id,name",
        })
        name_map = {m["id"]: m["name"] for m in mrows}
    for r in losses:
        r["_module_name"] = name_map.get(r.get("module_id"), r.get("module_id", "?")[:8])
    return losses


def _fmt_breaker_alert(cd_iso: str, streak_losses: list[dict], trips: int,
                       consecutive_losses: int, streak_by_module: dict) -> str:
    """Detailed breaker alert.

    Naming: there is ONE circuit breaker, project-wide (settings.circuit_breaker).
    It counts CONSECUTIVE losses ACROSS ALL MODULES. Trip = 5-in-a-row (see
    api/config.py circuit_breaker_max_consecutive_losses). Cooldown = 60min
    (circuit_breaker_cooldown_minutes). While tripped, risk_manager blocks
    every NEW entry from every module until cooldown expires.
    """
    lines = [
        "🛑 <b>CIRCUIT BREAKER TRIPPED</b>",
        f"<i>Bot-wide entry pause (Dublin auto-bot). Purpose: stop a losing streak "
        f"from bleeding capital by refusing NEW buys for 60 min. Open positions are "
        f"untouched; only new entries are blocked.</i>",
        "",
        f"<b>Paused until:</b> {_et(cd_iso)}",
        f"<b>Consecutive losses at trip:</b> {consecutive_losses if consecutive_losses else 'reset (counter cleared on trip)'}",
        f"<b>Lifetime trips:</b> #{trips}",
        "",
    ]
    if streak_losses:
        total = sum(float(r.get("realized_pnl") or 0) for r in streak_losses)
        lines.append(f"<b>Losing streak: {len(streak_losses)} in a row · ${total:+.2f} net</b>")
        # Which module(s) drove the streak
        if streak_by_module:
            per_mod = " · ".join(f"{n} ({c})" for n, c in streak_by_module.items())
            lines.append(f"<b>By module:</b> {per_mod}")
        lines.append("")
        for r in streak_losses:
            pnl = float(r.get("realized_pnl") or 0)
            avg = float(r.get("avg_price") or 0)
            exit_p = float(r.get("exit_price") or 0)
            lines.append(
                f"  • <b>{r['_module_name']}</b> {r.get('bracket','?')} · "
                f"${avg:.3f} → ${exit_p:.3f} · <b>${pnl:+.2f}</b> · {_et(r.get('closed_at'))}"
            )
    else:
        lines.append("<i>(Streak positions not found — inspect positions table. "
                     "This can happen if the streak was pre-migration or the counter "
                     "was manually bumped.)</i>")
    lines += ["", "<i>Auto-resumes at the time above. To force resume early, "
              "clear settings.circuit_breaker.cooldown_until in Supabase.</i>"]
    return "\n".join(lines)


def _fetch_recent_errors(since_iso: str) -> list[dict]:
    return _sb_get("logs", {
        "severity": "in.(error,critical)",
        "created_at": f"gte.{since_iso}",
        "select": "created_at,module_id,message",
        "order": "created_at.desc",
        "limit": "50",
    })


def _fmt_error_spike(errs: list[dict]) -> str:
    from collections import Counter
    # Group by first 80 chars of message so bursts of the same failure collapse
    keys = Counter(((e.get("message") or "")[:80]) for e in errs)
    top = keys.most_common(3)
    lines = [
        f"🔴 <b>ERROR SPIKE</b>: {len(errs)} error/critical logs in "
        f"{ERR_WINDOW_MIN:.0f}m (threshold {ERR_MAX})",
        f"Latest: {_et(errs[0]['created_at']) if errs else '-'}",
        "",
        "<b>Top messages:</b>",
    ]
    for msg, n in top:
        lines.append(f"  • ×{n} — <code>{msg}</code>")
    return "\n".join(lines)


def check() -> dict:
    """Return {condition_key: message or None}. None = healthy."""
    out: dict[str, str | None] = {}
    now = _now()

    # 1. Engine stale
    cyc = _sb_get("logs", {
        "log_type": "eq.system", "message": "like.Cycle:*",
        "select": "created_at", "order": "created_at.desc", "limit": "1"})
    if not cyc:
        out["engine"] = "🔴 <b>ENGINE</b>: no cycle logs at all"
    else:
        last_iso = cyc[0]["created_at"]
        age = (now - datetime.fromisoformat(last_iso.replace("Z", "+00:00"))).total_seconds() / 60
        if age > STALE_MIN:
            out["engine"] = (f"🔴 <b>ENGINE STALE</b>\n"
                             f"No cycle for <b>{age:.0f} min</b> (threshold {STALE_MIN:.0f}m)\n"
                             f"Last cycle: <b>{_et(last_iso)}</b>")
        else:
            out["engine"] = None

    # 2. Modules down
    dead = _sb_get("modules", {
        "status": "eq.inactive", "select": "name,inactive_reason,updated_at",
        "inactive_reason": "in.(kill_switch,error,data_stale,circuit_breaker)"})
    if dead:
        lines = ["🔴 <b>MODULE(S) DOWN</b>"]
        for m in dead:
            lines.append(f"  • <b>{m['name']}</b> — {m.get('inactive_reason')}"
                         f" · since {_et(m.get('updated_at'))}")
        out["modules"] = "\n".join(lines)
    else:
        out["modules"] = None

    # 3. Circuit breaker
    br = _sb_get("settings", {"key": "eq.circuit_breaker", "select": "value", "limit": "1"})
    br_val = (br[0]["value"] if br else {}) or {}
    cd = br_val.get("cooldown_until") or ""
    if cd and cd > now.isoformat():
        try:
            streak = _fetch_losing_streak()
        except Exception as e:
            streak = []
            print(f"[watchdog] streak fetch failed: {e}", flush=True)
        trips = int(br_val.get("trips") or 0)
        consecutive = int(br_val.get("consecutive_losses") or 0)
        # Count losses per module for the summary line
        from collections import Counter
        by_mod = Counter(r["_module_name"] for r in streak)
        out["breaker"] = _fmt_breaker_alert(cd, streak, trips, consecutive, dict(by_mod))
    else:
        out["breaker"] = None

    # 4. Error spike
    since_iso = datetime.fromtimestamp(now.timestamp() - ERR_WINDOW_MIN * 60, timezone.utc).isoformat()
    errs = _fetch_recent_errors(since_iso)
    if len(errs) > ERR_MAX:
        out["errors"] = _fmt_error_spike(errs)
    else:
        out["errors"] = None
    return out


def run_once() -> None:
    try:
        conditions = check()
    except Exception as e:
        print(f"[watchdog] check failed: {e}", flush=True)
        return
    state = load_state()
    stamp = _et(_now())
    changed = False
    for key, msg in conditions.items():
        prev = state.get(key) or {}
        was_bad = bool(prev.get("bad"))
        if msg:  # currently bad
            last = prev.get("last_alert_at") or ""
            due = (not was_bad) or (
                last and (_now() - datetime.fromisoformat(last)).total_seconds() / 60 >= REALERT_MIN)
            if due:
                telegram(f"{msg}\n\n<i>Bot: polybot (Dublin) · {stamp}</i>")
                state[key] = {"bad": True, "last_alert_at": _now().isoformat()}
                changed = True
        elif was_bad:  # recovered
            telegram(f"✅ <b>RECOVERED</b>: {key} is healthy again · {stamp}")
            state[key] = {"bad": False}
            changed = True
    if changed:
        save_state(state)
    bad = [k for k, v in conditions.items() if v]
    print(f"[watchdog] {stamp} checked; bad={bad or 'none'}", flush=True)


def main() -> None:
    print(f"[watchdog] starting; interval={INTERVAL_SEC}s stale={STALE_MIN}m ET", flush=True)
    telegram(f"🐕 Watchdog online · monitoring polybot · {_et(_now())}")
    while True:
        run_once()
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
