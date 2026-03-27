import math
import logging
import asyncio
from datetime import datetime, timezone
from api.dependencies import get_supabase
from api.modules.truth_social.data import fetch_market_prices

log = logging.getLogger(__name__)


def check_resolutions():
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    modules = (
        sb.table("modules")
        .select("id,name,market_slug,resolution_date")
        .not_.is_("resolution_date", "null")
        .in_("status", ["active", "paused", "paper"])
        .execute()
    )

    if not modules.data:
        return

    for module in modules.data:
        res_date = module["resolution_date"]
        if res_date > now:
            continue

        try:
            _resolve_module(sb, module)
        except Exception as e:
            log.error(f"Resolution failed for module {module['name']}: {e}")
            sb.table("logs").insert({
                "log_type": "system",
                "severity": "error",
                "module_id": module["id"],
                "message": f"Resolution error: {e}",
            }).execute()


def _resolve_module(sb, module):
    module_id = module["id"]
    slug = module.get("market_slug")
    if not slug:
        log.warning(f"Module {module['name']} has no market_slug, skipping resolution")
        return

    final_prices = asyncio.get_event_loop().run_until_complete(fetch_market_prices(slug))
    if not final_prices:
        log.warning(f"No final prices for {slug}, retrying next cycle")
        return

    winning_bracket = max(final_prices, key=final_prices.get)
    log.info(f"Resolving {module['name']}: winner={winning_bracket}, prices={final_prices}")

    positions = (
        sb.table("positions")
        .select("*")
        .eq("module_id", module_id)
        .eq("status", "open")
        .execute()
    )

    for pos in (positions.data or []):
        bracket = pos["bracket"]
        exit_price = final_prices.get(bracket, 0.0)
        pnl = (exit_price - pos["avg_price"]) * pos["size"]
        if pos["side"] == "SELL":
            pnl = -pnl

        sb.table("positions").update({
            "status": "closed",
            "exit_price": exit_price,
            "realized_pnl": round(pnl, 6),
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", pos["id"]).execute()

    _record_calibration(sb, module_id, slug, final_prices, winning_bracket)

    sb.table("modules").update({"status": "resolved"}).eq("id", module_id).execute()

    sb.table("logs").insert({
        "log_type": "execution",
        "severity": "info",
        "module_id": module_id,
        "message": f"Module resolved: winner={winning_bracket}",
        "metadata": {"final_prices": final_prices, "winning_bracket": winning_bracket},
    }).execute()

    log.info(f"Module {module['name']} resolved successfully")


def _record_calibration(sb, module_id, market_slug, final_prices, winning_bracket):
    signals = (
        sb.table("signals")
        .select("bracket,model_prob,market_id")
        .eq("module_id", module_id)
        .execute()
    )

    seen = set()
    for sig in (signals.data or []):
        bracket = sig.get("bracket")
        if not bracket or bracket in seen:
            continue
        seen.add(bracket)

        predicted_prob = sig.get("model_prob", 0.5)
        actual = bracket == winning_bracket
        outcome = 1.0 if actual else 0.0

        brier = (predicted_prob - outcome) ** 2
        clamped = max(0.001, min(0.999, predicted_prob))
        log_loss_val = -(outcome * math.log(clamped) + (1 - outcome) * math.log(1 - clamped))

        sb.table("calibration_log").insert({
            "module_id": module_id,
            "market_id": sig.get("market_id", market_slug),
            "bracket": bracket,
            "predicted_prob": predicted_prob,
            "actual_outcome": actual,
            "brier_score": round(brier, 6),
            "log_loss": round(log_loss_val, 6),
        }).execute()
