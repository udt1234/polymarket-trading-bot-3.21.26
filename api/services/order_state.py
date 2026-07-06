"""Order lifecycle state machine (BUILD_SPEC E5/E6).

States: submitted -> open -> (partially_filled) -> filled -> confirmed.
Also: cancelled, rejected. NEVER mark filled on the POST ack - only the
user WS channel / fill poller moves an order past 'submitted'.

Ghost fills (E6): an off-chain MATCHED trade is PROVISIONAL until on-chain
settlement confirms. 'filled' here means matched; 'confirmed' means the
settlement transaction is final. Risk keeps counting unconfirmed exposure.
"""
import logging
from datetime import datetime, timezone

from api.dependencies import get_supabase

log = logging.getLogger(__name__)

# Terminal states never move backwards.
_TERMINAL = {"confirmed", "cancelled", "rejected", "settled"}
_RANK = {"created": 0, "submitted": 1, "open": 2, "partially_filled": 3,
         "filled": 4, "confirmed": 5, "settled": 6}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_submitted(*, module_id: str | None, market_id: str, bracket: str,
                     side: str, price: float, size: float, token_id: str,
                     clob_order_id: str, executor: str = "live",
                     order_type: str = "GTC", metadata: dict | None = None) -> dict:
    """Insert the orders row the moment the CLOB ACKs the POST."""
    sb = get_supabase()
    row = {
        "module_id": module_id,
        "market_id": market_id,
        "bracket": bracket,
        "side": side.upper(),
        "size": size,
        "price": price,
        "status": "submitted",
        "executor": executor,
        "token_id": token_id,
        "clob_order_id": clob_order_id,
        "post_only": True,
        "order_type": order_type,
        "metadata": metadata or {},
    }
    res = sb.table("orders").insert(row).execute()
    return (res.data or [row])[0]


def advance(clob_order_id: str, new_status: str, *, size_filled: float | None = None) -> bool:
    """Move an order forward through the state machine. Refuses to move a
    terminal order or to go backwards (a late 'open' event after 'filled'
    must not regress the row). Returns True when a row was updated."""
    sb = get_supabase()
    res = (sb.table("orders").select("id,status,size_filled")
           .eq("clob_order_id", clob_order_id).limit(1).execute())
    if not res.data:
        log.warning("advance(%s -> %s): no orders row", clob_order_id, new_status)
        return False
    row = res.data[0]
    cur = row["status"]
    if cur in _TERMINAL:
        return False
    if new_status in ("cancelled", "rejected"):
        pass  # always allowed from a non-terminal state
    elif _RANK.get(new_status, -1) <= _RANK.get(cur, 99):
        return False
    patch: dict = {"status": new_status}
    if size_filled is not None:
        # Monotonic: never shrink the filled size on out-of-order events.
        patch["size_filled"] = max(float(size_filled), float(row.get("size_filled") or 0))
    if new_status == "filled":
        patch["filled_at"] = _now()
    sb.table("orders").update(patch).eq("id", row["id"]).execute()
    log.info("order %s: %s -> %s%s", clob_order_id[:16], cur, new_status,
             f" (filled {size_filled})" if size_filled is not None else "")
    return True
