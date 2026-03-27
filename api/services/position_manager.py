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
