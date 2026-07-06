"""Our own order/fill updates (BUILD_SPEC C5, E5, E6).

Two sources, stream preferred:
1. UserChannelStream - authenticated CLOB user WebSocket. Streams PLACEMENT /
   UPDATE / CANCELLATION order events and MATCHED / MINED / CONFIRMED trade
   events for OUR wallet. Includes a stall watchdog (a half-open socket looks
   alive but captures nothing).
2. reconcile_open_orders() - REST poller fallback run on the slow path; also
   the on-chain confirmation sweep (trade status CONFIRMED = settled on
   Polygon; MATCHED alone is provisional, E6).
"""
import asyncio
import json
import logging
import time

from api.config import get_settings
from api.services import order_state

log = logging.getLogger(__name__)

USER_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
PING_INTERVAL_S = 10
STALL_TIMEOUT_S = 40

# CLOB order event type -> our state
_ORDER_EVENT_STATE = {
    "PLACEMENT": "open",
    "CANCELLATION": "cancelled",
}
# CLOB trade status -> our state (E6: MATCHED is provisional; FAILED is
# handled explicitly in handle_user_message, never via this map)
_TRADE_STATUS_STATE = {
    "MATCHED": "filled",
    "MINED": "filled",
    "CONFIRMED": "confirmed",
}


def handle_user_message(msg: dict) -> None:
    """Apply one user-channel event to the orders state machine."""
    event_type = (msg.get("event_type") or "").lower()
    if event_type == "order":
        etype = (msg.get("type") or "").upper()
        oid = msg.get("id") or msg.get("orderID") or ""
        if not oid:
            return
        if etype == "UPDATE":
            matched = float(msg.get("size_matched") or 0)
            original = float(msg.get("original_size") or 0)
            state = "filled" if original and matched >= original else "partially_filled"
            order_state.advance(oid, state, size_filled=matched)
        elif etype in _ORDER_EVENT_STATE:
            order_state.advance(oid, _ORDER_EVENT_STATE[etype])
    elif event_type == "trade":
        status = (msg.get("status") or "").upper()
        if status == "FAILED":
            log.error("GHOST FILL: trade %s FAILED on-chain - reconcile before counting a loss: %s",
                      msg.get("id"), msg)
            return
        state = _TRADE_STATUS_STATE.get(status)
        if not state:
            return
        for mo in msg.get("maker_orders") or []:
            oid = mo.get("order_id") or ""
            if oid:
                order_state.advance(oid, state,
                                    size_filled=float(mo.get("matched_amount") or 0) or None)
        taker_oid = msg.get("taker_order_id") or ""
        if taker_oid:
            order_state.advance(taker_oid, state)


class UserChannelStream:
    """Persistent authenticated user-channel subscription with exponential
    backoff reconnect and a stall watchdog."""

    def __init__(self, on_message=handle_user_message, markets: list[str] | None = None,
                 auth: dict | None = None):
        self.on_message = on_message
        self.markets = markets or []
        self._auth = auth
        self._stop = asyncio.Event()
        self.last_msg_ts: float | None = None
        self.connected = False

    async def run(self):
        import websockets
        s = get_settings()
        auth = self._auth or {"apiKey": s.polymarket_api_key, "secret": s.polymarket_secret,
                              "passphrase": s.polymarket_passphrase}
        backoff = 1
        while not self._stop.is_set():
            try:
                async with websockets.connect(USER_WS_URL, ping_interval=None) as ws:
                    await ws.send(json.dumps({"type": "user", "auth": auth,
                                              "markets": self.markets}))
                    self.connected = True
                    self.last_msg_ts = time.time()
                    backoff = 1
                    log.info("User WS connected (%d markets)", len(self.markets))
                    ping_task = asyncio.create_task(self._pinger(ws))
                    try:
                        async for raw in ws:
                            self.last_msg_ts = time.time()
                            if raw == "PONG" or not raw:
                                continue
                            try:
                                payload = json.loads(raw)
                            except (TypeError, ValueError):
                                continue
                            for msg in payload if isinstance(payload, list) else [payload]:
                                try:
                                    self.on_message(msg)
                                except Exception:
                                    log.exception("user WS handler failed on %s", msg)
                    finally:
                        ping_task.cancel()
            except Exception as e:
                if self._stop.is_set():
                    break
                log.warning("User WS dropped (%s) - reconnect in %ds", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                self.connected = False

    async def _pinger(self, ws):
        """App-level PING + stall watchdog: no traffic for STALL_TIMEOUT_S
        (despite pings) means a half-open socket - force a reconnect."""
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            await ws.send("PING")
            if self.last_msg_ts and time.time() - self.last_msg_ts > STALL_TIMEOUT_S:
                log.warning("User WS stalled >%ds - forcing reconnect", STALL_TIMEOUT_S)
                await ws.close()
                return

    def stop(self):
        self._stop.set()


def reconcile_open_orders() -> int:
    """Slow-path REST reconciliation (fallback when the stream misses events,
    and the on-chain CONFIRMED sweep). Returns rows advanced."""
    from api.dependencies import get_supabase
    from api.services import clob
    sb = get_supabase()
    res = (sb.table("orders").select("clob_order_id,status,size")
           .eq("post_only", True).neq("executor", "paper")
           .in_("status", ["submitted", "open", "partially_filled", "filled"])
           .not_.is_("clob_order_id", "null").execute())
    rows = res.data or []
    if not rows:
        return 0
    advanced = 0
    open_ids = {o.get("id") for o in clob.get_open_orders()}
    for row in rows:
        oid = row["clob_order_id"]
        try:
            if row["status"] in ("submitted",) and oid in open_ids:
                advanced += order_state.advance(oid, "open")
                continue
            if oid in open_ids:
                continue
            # Not on the book anymore: filled, cancelled, or expired.
            order = clob.get_order(oid) or {}
            status = (order.get("status") or "").upper()
            matched = float(order.get("size_matched") or 0)
            if status == "CANCELED" and matched == 0:
                advanced += order_state.advance(oid, "cancelled")
            elif matched > 0:
                new = "filled" if matched >= float(row["size"]) else "partially_filled"
                advanced += order_state.advance(oid, new, size_filled=matched)
        except Exception:
            log.exception("reconcile failed for %s", oid)
    return advanced
