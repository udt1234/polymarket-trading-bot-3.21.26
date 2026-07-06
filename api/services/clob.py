"""CLOB V2 client wrapper (BUILD_SPEC E1-E3, J4).

Every order in this codebase goes through place_post_only(): post-only limit
orders, GTC/GTD only. The bot is a MAKER, never a taker. There is no code
path that submits a marketable/FOK/FAK order.

V2 notes (verified 2026-07-01/03):
- py_clob_client >= 0.34 signs V2 (exchange domain "2", ms timestamp, no nonce).
- post_only=True: would-cross -> rejected INVALID_POST_ONLY_ORDER (never takes).
- HTTP 425 = matching-engine restart: back off, pause new entries; cancels
  still accepted and the engine runs post-only for ~2 min (favors us).
- Use typed dataclasses (OrderArgs, ApiCreds); dicts crash later in the SDK.
"""
import logging
import math
import time

from api.config import get_settings
from api.services.polymarket_proxy import clob_host

log = logging.getLogger(__name__)

CHAIN_ID = 137  # Polygon
DEFAULT_TICK = 0.01  # standard markets; 0.001 on neg-risk markets
MIN_SHARES = 5.0
MIN_NOTIONAL = 1.0  # dollars

_client = None


class OrderValidationError(ValueError):
    pass


def get_clob_client():
    """Singleton py_clob_client. Raises when credentials are missing -
    callers must not fall back to an unauthenticated client silently."""
    global _client
    if _client is None:
        s = get_settings()
        if not all([s.polymarket_api_key, s.polymarket_secret,
                    s.polymarket_passphrase, s.polymarket_private_key]):
            raise RuntimeError("Missing Polymarket credentials (POLYMARKET_* env)")
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
        _client = ClobClient(
            host=clob_host(),
            key=s.polymarket_private_key,
            chain_id=CHAIN_ID,
            creds=ApiCreds(
                api_key=s.polymarket_api_key,
                api_secret=s.polymarket_secret,
                api_passphrase=s.polymarket_passphrase,
            ),
        )
    return _client


def snap_price(price: float, tick: float = DEFAULT_TICK) -> float:
    """Snap a price onto the market tick grid (E3)."""
    if tick <= 0:
        raise OrderValidationError(f"bad tick {tick}")
    snapped = round(round(price / tick) * tick, 6)
    return max(tick, min(snapped, round(1 - tick, 6)))


def validate_order(price: float, size: float, tick: float = DEFAULT_TICK) -> tuple[float, float]:
    """Enforce the three CLOB minimums at build time (E3):
    price on tick, >= 5 shares, >= $1 notional. Returns (price, size)
    with size rounded to whole shares. Raises OrderValidationError."""
    price = snap_price(price, tick)
    size = float(math.floor(size))
    if size < MIN_SHARES:
        raise OrderValidationError(f"size {size} below CLOB minimum {MIN_SHARES} shares")
    if price * size < MIN_NOTIONAL:
        raise OrderValidationError(
            f"notional ${price * size:.2f} below CLOB minimum ${MIN_NOTIONAL:.2f}")
    return price, size


def _with_backoff(fn, *args, attempts: int = 4, **kwargs):
    """Retry with exponential backoff (0.5/1/2s). HTTP 425 (matching-engine
    restart) and 5xx are retryable; anything else re-raises immediately."""
    delay = 0.5
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            retryable = status in (425, 500, 502, 503, 504) or "425" in str(e)
            if not retryable or i == attempts - 1:
                raise
            log.warning("CLOB %s retryable (%s), backoff %.1fs", fn.__name__, e, delay)
            time.sleep(delay)
            delay *= 2
    return None


def place_post_only(token_id: str, side: str, price: float, size: float,
                    tick: float = DEFAULT_TICK, expires_in_s: int | None = None) -> dict:
    """Place a post-only limit order. side: 'BUY' | 'SELL'.
    expires_in_s -> GTD with expiration = now + 60 + N (60s safety threshold,
    E2); None -> GTC. Returns the raw CLOB response dict (contains orderID).
    The response is an ACK, not a fill (B1)."""
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL

    price, size = validate_order(price, size, tick)
    args = OrderArgs(
        token_id=token_id,
        price=price,
        size=size,
        side=BUY if side.upper() == "BUY" else SELL,
    )
    if expires_in_s is not None:
        args.expiration = str(int(time.time()) + 60 + int(expires_in_s))
        order_type = OrderType.GTD
    else:
        order_type = OrderType.GTC
    client = get_clob_client()
    signed = client.create_order(args)
    resp = _with_backoff(client.post_order, signed, orderType=order_type, post_only=True)
    log.info("post_only %s %s %.4f x %.0f -> %s", side, token_id[:16], price, size,
             (resp or {}).get("orderID") or resp)
    return resp


def cancel_order(order_id: str) -> dict:
    return _with_backoff(get_clob_client().cancel, order_id)


def cancel_orders(order_ids: list[str]) -> dict:
    return _with_backoff(get_clob_client().cancel_orders, order_ids)


def cancel_market(asset_id: str = "", market: str = "") -> dict:
    """Batch-cancel all our resting orders in one market - the hot path's
    single cancel call (E7)."""
    return _with_backoff(get_clob_client().cancel_market_orders,
                         market=market, asset_id=asset_id)


def cancel_all() -> dict:
    return _with_backoff(get_clob_client().cancel_all)


def get_open_orders(asset_id: str | None = None) -> list[dict]:
    from py_clob_client.clob_types import OpenOrderParams
    params = OpenOrderParams(asset_id=asset_id) if asset_id else None
    resp = _with_backoff(get_clob_client().get_orders, params)
    return resp or []


def get_order(order_id: str) -> dict:
    return _with_backoff(get_clob_client().get_order, order_id)


def get_trades(**kwargs) -> list[dict]:
    from py_clob_client.clob_types import TradeParams
    params = TradeParams(**kwargs) if kwargs else None
    resp = _with_backoff(get_clob_client().get_trades, params)
    return resp or []


def get_collateral_balance() -> dict:
    """Read the wallet's collateral (pUSD) balance/allowance at the CLOB."""
    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
    return _with_backoff(
        get_clob_client().get_balance_allowance,
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL),
    )
