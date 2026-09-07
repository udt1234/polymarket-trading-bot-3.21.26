"""Circuit breaker (BUILD_SPEC G2). Trips after N consecutive losses,
60-min cooldown, auto-reset. Counters PERSIST in the settings table and
reload on boot - a redeploy must not forget a trip.

PER MODULE since 2026-09-07. It used to be one global counter, so a single
losing module gated every other module's entries: Arb Scanner's losses blocked
21 S2 and 1 Copytrader signal in a day. State now lives under
`circuit_breaker:<module_id>`.

It also ESCALATES. The old breaker napped for 60 minutes and reset, forever - it
had tripped 87 times without ever concluding anything. A strategy that trips
repeatedly inside a day is not having a bad hour, it is losing, so after
ESCALATE_TRIPS trips in ESCALATE_WINDOW_H the module is paused (dead_thesis)
instead of being handed another cooldown.
"""
import logging
from datetime import datetime, timedelta, timezone

from api.config import get_settings
from api.dependencies import get_supabase

log = logging.getLogger(__name__)

KEY = "circuit_breaker"
ESCALATE_TRIPS = 5
ESCALATE_WINDOW_H = 24


def _key(module_id: str | None) -> str:
    return f"{KEY}:{module_id}" if module_id else KEY


def _load(sb, module_id: str | None = None) -> dict:
    res = sb.table("settings").select("value").eq("key", _key(module_id)).limit(1).execute()
    return (res.data[0].get("value") if res.data else None) or {
        "consecutive_losses": 0, "cooldown_until": "", "trips": 0, "trip_log": []}


def _save(sb, state: dict, module_id: str | None = None) -> None:
    sb.table("settings").upsert({"key": _key(module_id), "value": state}).execute()


def _pause_module(sb, module_id: str, trips: int) -> None:
    """Stop napping and take the module off the bench."""
    row = (sb.table("modules").select("name").eq("id", module_id).limit(1).execute().data) or []
    name = row[0]["name"] if row else module_id
    sb.table("modules").update({
        "status": "inactive", "inactive_reason": "dead_thesis",
        "inactive_detail": (f"circuit breaker tripped {trips}x in {ESCALATE_WINDOW_H}h "
                            f"- auto-paused {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    }).eq("id", module_id).execute()
    log.error("CIRCUIT BREAKER ESCALATED - %s paused after %d trips", name, trips)
    try:
        from api.services.notifications import notify
        notify(f"⛔ {name} auto-paused: circuit breaker tripped {trips}x in "
               f"{ESCALATE_WINDOW_H}h. It is not having a bad hour, it is losing.")
    except Exception:
        log.exception("breaker escalation alert failed")


def record_trade_result(realized_pnl: float, module_id: str | None = None) -> dict:
    """Call on every CLOSED position. Wins reset the streak; losses count
    toward the trip threshold."""
    s = get_settings()
    sb = get_supabase()
    state = _load(sb, module_id)
    if realized_pnl >= 0:
        state["consecutive_losses"] = 0
    else:
        state["consecutive_losses"] += 1
        if (s.circuit_breaker_enabled
                and state["consecutive_losses"] >= s.circuit_breaker_max_consecutive_losses):
            now = datetime.now(timezone.utc)
            until = now + timedelta(minutes=s.circuit_breaker_cooldown_minutes)
            state["cooldown_until"] = until.isoformat()
            state["trips"] = int(state.get("trips") or 0) + 1
            state["consecutive_losses"] = 0
            window_start = (now - timedelta(hours=ESCALATE_WINDOW_H)).isoformat()
            recent = [t for t in (state.get("trip_log") or []) if t > window_start]
            recent.append(now.isoformat())
            state["trip_log"] = recent
            _save(sb, state, module_id)
            if module_id and len(recent) >= ESCALATE_TRIPS:
                _pause_module(sb, module_id, len(recent))
                return state
            log.error("CIRCUIT BREAKER TRIPPED (%s) - new entries paused until %s",
                      module_id or "global", until)
            try:
                from api.services.notifications import notify
                notify(f"🛑 Circuit breaker tripped - entries paused until {until:%H:%M} UTC")
            except Exception:
                log.exception("breaker alert failed")
            return state
    _save(sb, state, module_id)
    return state


def is_tripped(module_id: str | None = None) -> bool:
    """Fail closed: unreadable breaker state blocks new entries."""
    try:
        state = _load(get_supabase(), module_id)
        until = state.get("cooldown_until") or ""
        return bool(until) and until > datetime.now(timezone.utc).isoformat()
    except Exception:
        log.exception("breaker read failed - failing CLOSED")
        return True
