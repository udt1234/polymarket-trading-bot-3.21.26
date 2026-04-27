import logging
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


def open_position(module_id: str, market_id: str, bracket: str, side: str, size: float, price: float):
    sb = get_supabase()
    existing = (
        sb.table("positions")
        .select("*")
        .eq("module_id", module_id)
        .eq("market_id", market_id)
        .eq("bracket", bracket)
        .eq("status", "open")
        .execute()
    )

    if existing.data:
        pos = existing.data[0]
        old_size = pos["size"]
        old_avg = pos["avg_price"]
        new_size = old_size + size
        new_avg = ((old_avg * old_size) + (price * size)) / new_size if new_size != 0 else 0
        sb.table("positions").update({"size": new_size, "avg_price": new_avg}).eq("id", pos["id"]).execute()
    else:
        sb.table("positions").insert({
            "module_id": module_id,
            "market_id": market_id,
            "bracket": bracket,
            "side": side,
            "size": size,
            "avg_price": price,
            "status": "open",
        }).execute()


def find_open_position(module_id: str, market_id: str, bracket: str) -> dict | None:
    """Look up the single open BUY position matching this module/market/bracket.
    Returns None if none found. Used by exit paths to discover what to close.
    Bot is BUY-side-only today; if SELL-entry is ever added, this needs updating.
    """
    sb = get_supabase()
    res = (
        sb.table("positions")
        .select("*")
        .eq("module_id", module_id)
        .eq("market_id", market_id)
        .eq("bracket", bracket)
        .eq("side", "BUY")
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def claim_position_for_exit(position_id: str) -> bool:
    """Atomically transition a position from 'open' -> 'closing' to claim it.

    Two concurrent exit cycles racing on the same position: only one will see
    rowcount > 0. The loser aborts before placing an order. Required because
    Supabase doesn't expose row locking — this is the cheapest safe alternative.
    """
    sb = get_supabase()
    res = (
        sb.table("positions")
        .update({"status": "closing"})
        .eq("id", position_id)
        .eq("status", "open")
        .execute()
    )
    return bool(res.data)


def release_position_after_failed_exit(position_id: str):
    """Roll a 'closing' position back to 'open' if the order didn't fill,
    so the next exit cycle can retry."""
    sb = get_supabase()
    sb.table("positions").update({"status": "open"}).eq("id", position_id).eq("status", "closing").execute()


def partial_close_position(position_id: str, sold_size: float, exit_price: float):
    """Reduce position size by `sold_size`. Used when a SELL fill was capped
    by depth and the remaining inventory should stay open. Realized PnL on
    the sold portion is recorded; the residual stays at the original avg_price."""
    sb = get_supabase()
    pos = sb.table("positions").select("*").eq("id", position_id).single().execute()
    if not pos.data:
        return None
    p = pos.data
    remaining = max((p.get("size") or 0) - sold_size, 0)
    realized = (exit_price - (p.get("avg_price") or 0)) * sold_size
    if p.get("side") == "SELL":
        realized = -realized
    sb.table("positions").update({
        "status": "open",
        "size": remaining,
        "realized_pnl": (p.get("realized_pnl") or 0) + realized,
    }).eq("id", position_id).execute()
    return realized


def close_position(position_id: str, exit_price: float):
    sb = get_supabase()
    pos = sb.table("positions").select("*").eq("id", position_id).single().execute()
    if not pos.data:
        return

    p = pos.data
    pnl = (exit_price - p["avg_price"]) * p["size"]
    if p["side"] == "SELL":
        pnl = -pnl

    sb.table("positions").update({
        "status": "closed",
        "exit_price": exit_price,
        "realized_pnl": pnl,
    }).eq("id", position_id).execute()

    return pnl
