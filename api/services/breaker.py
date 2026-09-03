"""Circuit breaker (BUILD_SPEC G2). Trips after N consecutive losses,
60-min cooldown, auto-reset. Counters PERSIST in the settings table and
reload on boot - a redeploy must not forget a trip."""
import logging
from datetime import datetime, timedelta, timezone

from api.config import get_settings
from api.dependencies import get_supabase

log = logging.getLogger(__name__)

KEY = "circuit_breaker"


def _load(sb) -> dict:
    res = sb.table("settings").select("value").eq("key", KEY).limit(1).execute()
    return (res.data[0].get("value") if res.data else None) or {
        "consecutive_losses": 0, "cooldown_until": "", "trips": 0}


def _save(sb, state: dict) -> None:
    sb.table("settings").upsert({"key": KEY, "value": state}).execute()


def record_trade_result(realized_pnl: float) -> dict:
    """Call on every CLOSED position. Wins reset the streak; losses count
    toward the trip threshold."""
    s = get_settings()
    sb = get_supabase()
    state = _load(sb)
    if realized_pnl >= 0:
        state["consecutive_losses"] = 0
    else:
        state["consecutive_losses"] += 1
        if (s.circuit_breaker_enabled
                and state["consecutive_losses"] >= s.circuit_breaker_max_consecutive_losses):
            until = datetime.now(timezone.utc) + timedelta(
                minutes=s.circuit_breaker_cooldown_minutes)
            state["cooldown_until"] = until.isoformat()
            state["trips"] = int(state.get("trips") or 0) + 1
            state["consecutive_losses"] = 0
            log.error("CIRCUIT BREAKER TRIPPED - new entries paused until %s", until)
            try:
                from api.services.notifications import notify
                notify(f"🛑 Circuit breaker tripped - entries paused until {until:%H:%M} UTC")
            except Exception:
                log.exception("breaker alert failed")
    _save(sb, state)
    return state


def is_tripped() -> bool:
    """Fail closed: unreadable breaker state blocks new entries."""
    try:
        state = _load(get_supabase())
        until = state.get("cooldown_until") or ""
        return bool(until) and until > datetime.now(timezone.utc).isoformat()
    except Exception:
        log.exception("breaker read failed - failing CLOSED")
        return True
