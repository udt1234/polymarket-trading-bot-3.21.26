"""Position lifecycle (BUILD_SPEC E5). Positions open/close ONLY on
confirmed fills, never on order submission. Realized P&L ACCUMULATES on
close (existing + new), never overwrites. closed_at is always set."""
import logging
from datetime import datetime, timezone

from api.dependencies import get_supabase

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_buy_fill(*, module_id: str | None, market_id: str, bracket: str,
                   token_id: str, price: float, size: float) -> dict:
    """Open or grow a position from a confirmed BUY fill (volume-weighted
    average price on top-ups)."""
    sb = get_supabase()
    q = (sb.table("positions").select("*").eq("market_id", market_id)
         .eq("bracket", bracket).eq("status", "open"))
    if module_id is not None:
        q = q.eq("module_id", module_id)
    res = q.limit(1).execute()
    row = (res.data or [None])[0]
    if row:
        old_size = float(row["size"]); old_avg = float(row["avg_price"])
        new_size = old_size + size
        new_avg = (old_size * old_avg + size * price) / new_size if new_size else 0
        sb.table("positions").update({"size": new_size, "avg_price": new_avg}) \
            .eq("id", row["id"]).execute()
        row.update({"size": new_size, "avg_price": new_avg})
        return row
    ins = {"module_id": module_id, "market_id": market_id, "bracket": bracket,
           "side": "BUY", "size": size, "avg_price": price, "status": "open",
           "token_id": token_id}
    return (sb.table("positions").insert(ins).execute().data or [ins])[0]


def claim_for_exit(position_id: str) -> bool:
    """Atomic claim to prevent double-sells: only one caller wins the
    open -> closing transition."""
    sb = get_supabase()
    res = (sb.table("positions").update({"status": "closing"})
           .eq("id", position_id).eq("status", "open").execute())
    return bool(res.data)


def apply_sell_fill(position_id: str, sell_price: float, sold_size: float) -> dict | None:
    """Close (or shrink) a position from a confirmed SELL fill. Realized
    P&L accumulates; full close sets closed_at."""
    sb = get_supabase()
    res = sb.table("positions").select("*").eq("id", position_id).limit(1).execute()
    row = (res.data or [None])[0]
    if not row:
        log.error("apply_sell_fill: position %s missing", position_id)
        return None
    size = float(row["size"]); avg = float(row["avg_price"])
    sold = min(sold_size, size)
    pnl_delta = (sell_price - avg) * sold
    remaining = size - sold
    patch = {"realized_pnl": float(row.get("realized_pnl") or 0) + pnl_delta,
             "size": remaining, "exit_price": sell_price}
    if remaining <= 1e-9:
        patch.update({"status": "closed", "closed_at": _now(), "size": 0})
    else:
        patch["status"] = "open"  # partial exit re-opens the remainder
    sb.table("positions").update(patch).eq("id", row["id"]).execute()
    row.update(patch)
    if patch.get("status") == "closed":
        try:
            from api.services.breaker import record_trade_result
            record_trade_result(float(row["realized_pnl"]))
        except Exception:
            log.exception("breaker update failed on close")
    return row


def resolve_at(position_id: str, settle_price: float) -> dict | None:
    """Resolution settlement: winning bracket -> 1.00, losers -> 0.00."""
    sb = get_supabase()
    res = sb.table("positions").select("size").eq("id", position_id).limit(1).execute()
    row = (res.data or [None])[0]
    if not row:
        return None
    if claim_for_exit(position_id) or True:  # resolution overrides claims
        return apply_sell_fill(position_id, settle_price, float(row["size"]))


def open_positions(module_id: str | None = None) -> list[dict]:
    sb = get_supabase()
    q = sb.table("positions").select("*").eq("status", "open")
    if module_id:
        q = q.eq("module_id", module_id)
    return q.execute().data or []


def sweep_stuck_closing(max_age_min: int = 30) -> int:
    """Rows stuck in 'closing' longer than N minutes revert to 'open'
    (the SELL never confirmed) so exits can retry."""
    from datetime import timedelta
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_min)).isoformat()
    res = (sb.table("positions").update({"status": "open"})
           .eq("status", "closing").lt("updated_at", cutoff).execute())
    n = len(res.data or [])
    if n:
        log.warning("swept %d stuck 'closing' positions back to open", n)
    return n
