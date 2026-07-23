"""Global manual halt (kill switch) - risk-audit F5, 2026-07-22.

A human operator override that STOPS new order placement AND cancels all resting
orders in one action. It does NOT liquidate positions: closing at avg_price would
realize losses at the worst moment (the 2026-05-16 lesson - /api/engine/stop was a
kill switch that closed positions; this must NOT repeat). Halt = stop + cancel, never
sell. Positions stay open and settle normally at resolution or via exit logic when
un-halted.

State lives in the settings table so it survives a redeploy (same pattern as the
breaker). The engine checks is_halted() at the top of each cycle and skips the module
loop while halted. Exits/resolution still run (they are not new placement).
"""
import logging

from api.dependencies import get_supabase

log = logging.getLogger(__name__)

_KEY = "global_halt"


def is_halted() -> bool:
    """Fail SAFE: an unreadable halt flag is treated as HALTED (stop placing)."""
    try:
        res = (get_supabase().table("settings").select("value")
               .eq("key", _KEY).limit(1).execute())
        return bool((res.data[0]["value"] or {}).get("halted")) if res.data else False
    except Exception:
        log.exception("halt read failed - failing SAFE (treating as halted)")
        return True


def set_halt(halted: bool, reason: str = "") -> dict:
    """Flip the halt flag. On halt, best-effort cancel all resting LIVE orders
    (paper has nothing to cancel on the exchange). Never touches positions."""
    sb = get_supabase()
    sb.table("settings").upsert({"key": _KEY, "value": {"halted": halted, "reason": reason}}).execute()
    cancelled = None
    if halted:
        try:
            from api.config import get_settings
            s = get_settings()
            live = s.environment == "production" and not s.paper_mode and s.allow_live_trading
            if live:
                from api.services import clob
                cancelled = clob.cancel_all()
        except Exception:
            log.exception("halt: cancel_all failed (flag still set)")
        try:
            from api.services.notifications import notify
            notify(f"🛑 GLOBAL HALT engaged{': ' + reason if reason else ''} - new orders stopped, resting orders cancelled. Positions untouched.")
        except Exception:
            pass
    try:
        sb.table("logs").insert({
            "log_type": "system", "severity": "warning" if halted else "info",
            "message": f"global halt {'ENGAGED' if halted else 'RELEASED'}: {reason}",
            "metadata": {"halted": halted, "reason": reason, "cancelled": cancelled}}).execute()
    except Exception:
        pass
    return {"halted": halted, "reason": reason, "cancelled": cancelled}
