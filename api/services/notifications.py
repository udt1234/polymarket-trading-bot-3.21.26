"""Telegram/Slack notifications (BUILD_SPEC I4). Read-only observers of the
bot; never trade. The daily heartbeat fires at 9 AM and 5 PM ET regardless
of health - a MISSING message means the bot is dead."""
import logging

import httpx

from api.config import get_settings

log = logging.getLogger(__name__)


def notify(text: str) -> bool:
    """Best-effort: Telegram first, Slack fallback. Returns delivery success."""
    s = get_settings()
    ok = False
    if s.telegram_bot_token and s.telegram_chat_id:
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={"chat_id": s.telegram_chat_id, "text": text}, timeout=15)
            ok = r.status_code == 200
            if not ok:
                log.error("telegram send failed %s: %s", r.status_code, r.text[:200])
        except Exception:
            log.exception("telegram send failed")
    if not ok and s.slack_webhook_url:
        try:
            r = httpx.post(s.slack_webhook_url, json={"text": text}, timeout=15)
            ok = r.status_code == 200
        except Exception:
            log.exception("slack send failed")
    return ok


def daily_heartbeat(engine) -> None:
    from api.dependencies import get_supabase
    from api.services.breaker import is_tripped
    sb = get_supabase()
    try:
        open_pos = (sb.table("positions").select("id", count="exact")
                    .eq("status", "open").execute().count) or 0
        resting = (sb.table("orders").select("id", count="exact")
                   .in_("status", ["submitted", "open"]).execute().count) or 0
    except Exception:
        open_pos = resting = -1
    notify(
        f"🫀 Bot heartbeat | cycles={engine.cycles} last={engine.last_cycle_at} "
        f"| open positions={open_pos} resting orders={resting} "
        f"| breaker={'TRIPPED' if is_tripped() else 'ok'}")
