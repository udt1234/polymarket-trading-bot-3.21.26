import math
import json
import logging
import httpx
from datetime import datetime, timezone
from collections import defaultdict
from api.dependencies import get_supabase

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"


def _fetch_prices_sync(slug: str) -> dict[str, float]:
    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
            res.raise_for_status()
            events = res.json()
            if not isinstance(events, list) or not events:
                return {}
            prices = {}
            for m in events[0].get("markets", []):
                raw = m.get("groupItemTitle", m.get("question", ""))
                op = m.get("outcomePrices", "[]")
                if isinstance(op, str):
                    op = json.loads(op)
                if op and raw:
                    p = float(op[0])
                    if 0 <= p <= 1:
                        prices[raw] = p
            return prices
    except Exception as e:
        log.warning(f"Price fetch failed for {slug}: {e}")
        return {}


def _is_market_resolved(slug: str) -> tuple[bool, str | None]:
    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
            events = res.json()
            if not events:
                return False, None
            markets = events[0].get("markets", [])
            if not markets:
                return False, None
            resolved = all(m.get("closed") or m.get("resolved") for m in markets)
            if resolved:
                winner = None
                best_price = -1
                for m in markets:
                    raw = m.get("groupItemTitle", m.get("question", ""))
                    op = m.get("outcomePrices", "[]")
                    if isinstance(op, str):
                        op = json.loads(op)
                    if op:
                        p = float(op[0])
                        if p > best_price:
                            best_price = p
                            winner = raw
                return True, winner
            return False, None
    except Exception:
        return False, None


def check_resolutions(risk_manager=None):
    sb = get_supabase()

    open_positions = sb.table("positions").select("*").eq("status", "open").execute()
    if not open_positions.data:
        return

    by_market = defaultdict(list)
    for pos in open_positions.data:
        market_id = pos.get("market_id", "")
        if market_id:
            by_market[market_id].append(pos)

    for market_id, positions in by_market.items():
        try:
            _resolve_market(sb, market_id, positions, risk_manager)
        except Exception as e:
            log.error(f"Resolution check failed for {market_id}: {e}")


def _resolve_market(sb, market_id: str, positions: list[dict], risk_manager=None):
    resolved, winner = _is_market_resolved(market_id)
    if not resolved:
        return

    final_prices = _fetch_prices_sync(market_id)
    if not final_prices:
        final_prices = {}
        if winner:
            for pos in positions:
                final_prices[pos["bracket"]] = 1.0 if pos["bracket"] == winner else 0.0

    winning_bracket = winner or (max(final_prices, key=final_prices.get) if final_prices else None)
    log.info(f"Resolving market {market_id}: winner={winning_bracket}")

    module_id = positions[0].get("module_id") if positions else None

    for pos in positions:
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

        log.info(f"  Closed {bracket}: pnl=${pnl:.2f} (exit={exit_price:.4f})")

        if risk_manager:
            if pnl >= 0:
                risk_manager.record_win()
            else:
                risk_manager.record_loss()

    if module_id:
        _record_calibration(sb, module_id, market_id, final_prices, winning_bracket)

    sb.table("logs").insert({
        "log_type": "execution",
        "severity": "info",
        "module_id": module_id,
        "message": f"Market resolved: {market_id}, winner={winning_bracket}",
        "metadata": {"market_id": market_id, "final_prices": final_prices, "winning_bracket": winning_bracket},
    }).execute()

    log.info(f"Market {market_id} resolved: {len(positions)} positions closed")


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
