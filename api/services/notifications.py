import httpx
import logging
from api.config import get_settings
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


async def send_slack(message: str, blocks: list[dict] | None = None):
    import os
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        try:
            sb = get_supabase()
            notif_settings = sb.table("settings").select("value").eq("key", "notifications").single().execute()
            if notif_settings.data:
                webhook_url = notif_settings.data.get("value", {}).get("slack_webhook")
        except Exception:
            pass

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


async def notify_auction_gap(handle: str, last_end: str, hours_gap: float):
    await send_slack(
        f":warning: *Auction Gap Detected* | {handle} | Last auction ended {last_end} | {hours_gap:.0f}h with no new auction | Check xTracker"
    )


async def notify_new_auction(handle: str, title: str, start: str, end: str):
    await send_slack(
        f":new: *New Auction* | {handle} | {title} | {start} → {end}"
    )


async def notify_divergence(
    handle: str, bracket: str, market_price: float, model_prob: float,
    running_total: int, hours_remaining: float, context: str = "",
):
    """Crowd-vs-model divergence: market priced high but model says unlikely.

    Concrete example: 200+ priced at 38% but model says 4% (running_total=198,
    4h left). The user wants these as Slack pings so they can manually take
    advantage (sell the 200+, buy the real winner).
    """
    delta = market_price - model_prob
    msg = (
        f":rotating_light: *Divergence Alert* | {handle} | bracket *{bracket}*\n"
        f"Market price *{market_price * 100:.1f}%* but model says *{model_prob * 100:.1f}%* "
        f"(delta {delta * 100:+.1f} pp)\n"
        f"Running total: *{running_total}*  |  Time left: *{hours_remaining:.1f}h*"
    )
    if context:
        msg += f"\n_{context}_"
    msg += "\nAction: consider selling the over-priced bracket or buying the real winner."
    await send_slack(msg)
