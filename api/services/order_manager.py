import logging
from enum import Enum
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    LIVE = "live"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    SETTLED = "settled"


VALID_TRANSITIONS = {
    OrderStatus.CREATED: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED},
    OrderStatus.SUBMITTED: {OrderStatus.LIVE, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.LIVE: {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.FILLED, OrderStatus.CANCELLED},
    OrderStatus.FILLED: {OrderStatus.SETTLED},
}


def transition_order(order_id: str, new_status: OrderStatus) -> bool:
    sb = get_supabase()
    order = sb.table("orders").select("status").eq("id", order_id).single().execute()
    if not order.data:
        return False

    current = OrderStatus(order.data["status"])
    if new_status not in VALID_TRANSITIONS.get(current, set()):
        log.warning(f"Invalid transition: {current} -> {new_status} for order {order_id}")
        return False

    sb.table("orders").update({"status": new_status.value}).eq("id", order_id).execute()
    return True
