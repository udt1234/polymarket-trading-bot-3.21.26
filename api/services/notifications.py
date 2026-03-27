import httpx
import logging
from api.config import get_settings
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


async def send_slack(message: str, blocks: list[dict] | None = None):
    sb = get_supabase()
    notif_settings = sb.table("settings").select("value").eq("key", "notifications").single().execute()
    webhook_url = None
    if notif_settings.data:
        webhook_url = notif_settings.data.get("value", {}).get("slack_webhook")

    if not webhook_url:
        log.debug("Slack webhook not configured — skipping notification")
        return False

    payload = {"text": message}
    if blocks:
        payload["blocks"] = blocks

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            res = await client.post(webhook_url, json=payload)
            res.raise_for_status()
            return True
        except Exception as e:
            log.error(f"Slack notification failed: {e}")
            return False


async def notify_trade_executed(side: str, bracket: str, size: float, price: float, executor: str):
    emoji = ":chart_with_upwards_trend:" if side == "BUY" else ":chart_with_downwards_trend:"
    await send_slack(
        f"{emoji} *{side}* {bracket} | Size: ${size:.2f} @ {price:.4f} | Mode: {executor}"
    )


async def notify_circuit_breaker(consecutive_losses: int, cooldown_minutes: int):
    await send_slack(
        f":rotating_light: *Circuit Breaker Tripped* | {consecutive_losses} consecutive losses | Cooldown: {cooldown_minutes}min"
    )


async def notify_daily_summary(portfolio_value: float, daily_return: float, total_pnl: float):
    emoji = ":white_check_mark:" if daily_return >= 0 else ":red_circle:"
    await send_slack(
        f"{emoji} *Daily Summary* | Value: ${portfolio_value:.2f} | Return: {daily_return:+.2%} | Total P&L: ${total_pnl:.2f}"
    )


async def notify_regime_shift(old_regime: str, new_regime: str, zscore: float):
    await send_slack(
        f":warning: *Regime Shift* | {old_regime} -> {new_regime} | Z-score: {zscore:.2f}"
    )


async def notify_walk_forward_alert(module_id: str, reason: str, action: str):
    await send_slack(
        f":microscope: *Walk-Forward Alert* | Module: {module_id} | {reason} | Action: {action}"
    )
