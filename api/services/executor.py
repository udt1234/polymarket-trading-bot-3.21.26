"""Executors (BUILD_SPEC G3, E5, J2).

LiveExecutor: post-only limit orders via the CLOB wrapper. Requires the
DUAL live guard - module status 'active' (checked by the engine router)
AND the env backstop (environment=production, paper_mode=false,
allow_live_trading=true) - and refuses to construct without credentials.
A POST ack only records 'submitted'; fills arrive via fills.py.

PaperExecutor: simulates a MAKER. A paper BUY rests and fills only when
best_ask <= our limit (J2); it never touches the CLOB. Fills write the
same positions/trades rows live fills would.
"""
import logging
import uuid
from datetime import datetime, timezone

from api.config import get_settings
from api.dependencies import get_supabase
from api.services import position_manager
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


def _record_signal(sb, signal: Signal, approved: bool, reason: str) -> None:
    try:
        sb.table("signals").insert({
            "module_id": signal.module_id, "market_id": signal.market_id,
            "bracket": signal.bracket, "side": signal.side,
            "edge": signal.edge, "model_prob": signal.fair_value,
            "market_price": signal.price, "approved": approved,
            "rejection_reason": None if approved else reason,
        }).execute()
    except Exception:
        log.exception("signal row write failed")


class LiveExecutor:
    name = "live"

    def __init__(self):
        s = get_settings()
        if not (s.environment == "production" and not s.paper_mode and s.allow_live_trading):
            raise RuntimeError(
                "LiveExecutor refused: dual live guard not satisfied "
                f"(environment={s.environment}, paper_mode={s.paper_mode}, "
                f"allow_live_trading={s.allow_live_trading})")
        from api.services.clob import get_clob_client
        get_clob_client()  # raises when credentials are missing

    def execute(self, signal: Signal) -> dict:
        from api.services import clob, order_state
        resp = clob.place_post_only(signal.token_id, signal.side, signal.price,
                                    signal.size)
        oid = (resp or {}).get("orderID")
        if not oid:
            return {"status": "rejected", "reason": str(resp)}
        order_state.record_submitted(
            module_id=signal.module_id, market_id=signal.market_id,
            bracket=signal.bracket, side=signal.side, price=signal.price,
            size=signal.size, token_id=signal.token_id, clob_order_id=oid,
            executor=self.name, metadata=signal.metadata)
        # Submitted != filled (B1). fills.py moves it forward.
        return {"status": "submitted", "clob_order_id": oid}


class PaperExecutor:
    name = "paper"

    def execute(self, signal: Signal) -> dict:
        sb = get_supabase()
        row = {
            "module_id": signal.module_id, "market_id": signal.market_id,
            "bracket": signal.bracket, "side": signal.side,
            "size": signal.size, "price": signal.price, "status": "open",
            "executor": "paper", "token_id": signal.token_id,
            "post_only": True, "order_type": "GTC",
            "clob_order_id": f"paper-{uuid.uuid4()}",
            "metadata": {**signal.metadata, "position_id": signal.metadata.get("position_id")},
        }
        sb.table("orders").insert(row).execute()
        log.info("PAPER rest %s %s %.4f x %.0f (%s)", signal.side, signal.bracket,
                 signal.price, signal.size, signal.auction_slug)
        return {"status": "open", "clob_order_id": row["clob_order_id"]}

    def check_fills(self, book_prices: dict[str, dict]) -> int:
        """Fill resting paper orders against live top-of-book. book_prices:
        token_id -> {best_bid, best_ask}. A maker BUY fills when best_ask
        <= limit; a maker SELL fills when best_bid >= limit. Returns fills."""
        sb = get_supabase()
        rows = (sb.table("orders").select("*").eq("executor", "paper")
                .eq("status", "open").execute().data) or []
        fills = 0
        for o in rows:
            quote = book_prices.get(o.get("token_id") or "")
            if not quote:
                continue
            price = float(o["price"]); size = float(o["size"])
            side = o["side"]
            crossed = (side == "BUY" and quote.get("best_ask") is not None
                       and quote["best_ask"] <= price) or \
                      (side == "SELL" and quote.get("best_bid") is not None
                       and quote["best_bid"] >= price)
            if not crossed:
                continue
            sb.table("orders").update({
                "status": "filled", "size_filled": size,
                "filled_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", o["id"]).execute()
            sb.table("trades").insert({
                "module_id": o.get("module_id"), "market_id": o.get("market_id"),
                "bracket": o.get("bracket"), "side": side, "size": size,
                "price": price,
            }).execute()
            if side == "BUY":
                position_manager.apply_buy_fill(
                    module_id=o.get("module_id"), market_id=o.get("market_id") or "",
                    bracket=o.get("bracket") or "", token_id=o.get("token_id") or "",
                    price=price, size=size)
            else:
                pos_id = (o.get("metadata") or {}).get("position_id")
                if pos_id:
                    position_manager.apply_sell_fill(pos_id, price, size)
            fills += 1
            log.info("PAPER FILL %s %s %.4f x %.0f", side, o.get("bracket"), price, size)
        return fills


def executor_for(module_status: str):
    """Route per-module: only status 'active' AND the env backstop reaches
    LiveExecutor; everything else is paper (G3)."""
    if module_status == "active":
        return LiveExecutor()
    return PaperExecutor()
