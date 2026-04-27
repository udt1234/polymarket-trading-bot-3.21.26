"""Crowd-vs-model divergence alerter.

Fires a Slack notification when:
1. Market price for a bracket is high (>= alert_market_price_min, default 0.20)
2. AND model_prob for that bracket is low (<= alert_model_prob_max, default 0.05)
3. AND the bracket is NOT already mathematically impossible (post-floor)

Throttled to one alert per (module_id, bracket, auction) per cool_down_hours
(default 6h) so the bot doesn't spam when divergence persists across cycles.
"""
import json
import logging
import time
from typing import Any

from api.dependencies import get_supabase
from api.services.notifications import notify_divergence

log = logging.getLogger(__name__)

# Defaults — overridable per-module via module_config.
DEFAULTS = {
    "divergence_alerts_enabled": True,
    "divergence_market_price_min": 0.20,   # market thinks >= 20% likely
    "divergence_model_prob_max": 0.05,     # model thinks <= 5% likely
    "divergence_cooldown_hours": 6.0,
}

_DEDUPE_KEY_PREFIX = "divergence_alert"


def _dedupe_key(module_id: str, bracket: str, market_id: str) -> str:
    return f"{_DEDUPE_KEY_PREFIX}:{module_id}:{market_id}:{bracket}"


def _was_recently_alerted(key: str, cooldown_hours: float) -> bool:
    try:
        sb = get_supabase()
        row = sb.table("settings").select("value").eq("key", key).execute()
        if not row.data:
            return False
        last_ts = (row.data[0].get("value") or {}).get("ts", 0)
        elapsed_hours = (time.time() - float(last_ts)) / 3600.0
        return elapsed_hours < cooldown_hours
    except Exception as e:
        log.warning(f"divergence dedupe lookup failed for {key}: {e}")
        return False


def _record_alert(key: str, payload: dict[str, Any]):
    try:
        sb = get_supabase()
        sb.table("settings").upsert({
            "key": key,
            "value": {**payload, "ts": time.time()},
        }).execute()
    except Exception as e:
        log.warning(f"divergence dedupe record failed for {key}: {e}")


async def check_and_alert_divergences(
    handle: str,
    module_id: str,
    market_id: str,
    bracket_probs: dict[str, float],
    market_prices: dict[str, float],
    running_total: int,
    hours_remaining: float,
    config: dict[str, Any] | None = None,
) -> list[dict]:
    """Scan bracket_probs vs market_prices for divergences and fire alerts.

    Returns the list of alerts that were sent (empty if none / disabled).
    bracket_probs should already have the running_total floor applied so
    impossible brackets aren't flagged as divergences.
    """
    cfg = {**DEFAULTS, **(config or {})}
    if not cfg.get("divergence_alerts_enabled"):
        return []

    market_min = float(cfg.get("divergence_market_price_min") or DEFAULTS["divergence_market_price_min"])
    model_max = float(cfg.get("divergence_model_prob_max") or DEFAULTS["divergence_model_prob_max"])
    cooldown = float(cfg.get("divergence_cooldown_hours") or DEFAULTS["divergence_cooldown_hours"])

    alerts_sent = []
    for bracket, market_price in market_prices.items():
        if market_price is None or market_price < market_min:
            continue
        model_prob = bracket_probs.get(bracket)
        if model_prob is None or model_prob > model_max:
            continue
        # Skip already-impossible brackets — the floor zeros them but a stale
        # ensemble payload could still feed in. Defensive double-check.
        if model_prob <= 0:
            continue

        key = _dedupe_key(module_id, bracket, market_id)
        if _was_recently_alerted(key, cooldown):
            continue

        context = (
            f"Crowd thinks this bracket is likely; model disagrees strongly. "
            f"Cooldown {cooldown:.0f}h before next alert on this bracket."
        )
        try:
            await notify_divergence(
                handle, bracket, float(market_price), float(model_prob),
                running_total, hours_remaining, context=context,
            )
            _record_alert(key, {
                "bracket": bracket,
                "market_price": float(market_price),
                "model_prob": float(model_prob),
                "running_total": running_total,
                "hours_remaining": hours_remaining,
            })
            alerts_sent.append({
                "bracket": bracket,
                "market_price": float(market_price),
                "model_prob": float(model_prob),
            })
        except Exception as e:
            log.error(f"divergence notify failed for {bracket}: {e}")

    if alerts_sent:
        log.info(f"divergence_detector: fired {len(alerts_sent)} alerts for {handle} ({market_id})")
    return alerts_sent
