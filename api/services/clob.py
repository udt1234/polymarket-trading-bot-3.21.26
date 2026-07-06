"""CLOB client wrapper (BUILD_SPEC E1-E3, J4) on the official polymarket-client
SDK (Polymarket py-sdk).

IMPORTANT (discovered 2026-07-06 on the Dublin box): py_clob_client is
ARCHIVED and can no longer place orders - every order it signs is rejected
with 'invalid order version'. The replacement is the unified SDK
`polymarket-client` (github.com/Polymarket/py-sdk), which signs current-
version orders, auto-detects wallet type, resolves tick size/neg-risk per
token, and derives L2 credentials from the private key.

Every order in this codebase goes through place_post_only(): post-only
limit orders only. The bot is a MAKER, never a taker - there is no code
path that submits a market/FAK order.
"""
import logging
import math
import time

from api.config import get_settings

log = logging.getLogger(__name__)

DEFAULT_TICK = 0.01  # standard markets; 0.001 on neg-risk (SDK re-validates)
MIN_SHARES = 5.0
MIN_NOTIONAL = 1.0  # dollars
GTD_MIN_HORIZON_S = 180  # SDK: expiration must be >= 3 min out

_client = None


class OrderValidationError(ValueError):
    pass


def get_clob_client():
    """Singleton SecureClient. Credentials are DERIVED from the private key
    (no separate api key/secret/passphrase needed). Raises when the key is
    missing - never falls back to an unauthenticated client."""
    global _client
    if _client is None:
        s = get_settings()
        if not s.polymarket_private_key:
            raise RuntimeError("Missing POLYMARKET_PRIVATE_KEY")
        from polymarket import SecureClient
        _client = SecureClient.create(
            private_key=s.polymarket_private_key,
            wallet=s.polymarket_wallet_address or None,
        )
    return _client


def snap_price(price: float, tick: float = DEFAULT_TICK) -> float:
    """Snap a price onto the market tick grid (E3)."""
    if tick <= 0:
        raise OrderValidationError(f"bad tick {tick}")
    snapped = round(round(price / tick) * tick, 6)
    return max(tick, min(snapped, round(1 - tick, 6)))


def validate_order(price: float, size: float, tick: float = DEFAULT_TICK) -> tuple[float, float]:
    """Enforce the CLOB minimums at build time (E3): price on tick,
    >= 5 shares, >= $1 notional. Returns (price, whole-share size)."""
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
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            retryable = status in (425, 500, 502, 503, 504) or "425" in str(e)
            if not retryable or i == attempts - 1:
                raise
            log.warning("CLOB %s retryable (%s), backoff %.1fs",
                        getattr(fn, "__name__", fn), e, delay)
            time.sleep(delay)
            delay *= 2
    return None


def _dump(model) -> dict:
    if model is None:
        return {}
    if isinstance(model, dict):
        return model
    try:
        return model.model_dump(mode="json", by_alias=False)
    except Exception:
        return {"repr": repr(model)}


def place_post_only(token_id: str, side: str, price: float, size: float,
                    tick: float = DEFAULT_TICK, expires_in_s: int | None = None) -> dict:
    """Place a post-only limit order. side: 'BUY' | 'SELL'. expires_in_s
    -> GTD with expiration >= now + 3 min (SDK minimum); None -> GTC.
    Returns {'orderID', 'success', ...}. The response is an ACK, not a
    fill (B1)."""
    price, size = validate_order(price, size, tick)
    kwargs: dict = {}
    if expires_in_s is not None:
        kwargs["expiration"] = int(time.time()) + max(int(expires_in_s), 0) + GTD_MIN_HORIZON_S
    client = get_clob_client()
    resp = _with_backoff(
        client.place_limit_order, token_id=token_id, price=price, size=size,
        side=side.upper(), post_only=True, **kwargs)
    out = _dump(resp)
    out.setdefault("orderID", getattr(resp, "order_id", None))
    log.info("post_only %s %s %.4f x %.0f -> %s", side, token_id[:16], price, size,
             out.get("orderID"))
    return out


def create_signed_post_only(token_id: str, side: str, price: float, size: float,
                            tick: float = DEFAULT_TICK):
    """Sign WITHOUT posting - the pre-sign loop's builder (E7)."""
    price, size = validate_order(price, size, tick)
    return get_clob_client().create_limit_order(
        token_id=token_id, price=price, size=size, side=side.upper(),
        post_only=True)


def post_signed(signed_orders: list) -> list[dict]:
    """Fire pre-signed orders (hot path step 2)."""
    resp = get_clob_client().post_orders(signed_orders)
    return [_dump(r) for r in (resp or [])]


def cancel_order(order_id: str) -> dict:
    return _dump(_with_backoff(get_clob_client().cancel_order, order_id=order_id))


def cancel_orders(order_ids: list[str]) -> dict:
    return _dump(_with_backoff(get_clob_client().cancel_orders, order_ids=order_ids))


def cancel_market(asset_id: str = "", market: str = "") -> dict:
    """Batch-cancel all our resting orders in one market - the hot path's
    single cancel call (E7)."""
    return _dump(_with_backoff(get_clob_client().cancel_market_orders,
                               market=market or None, token_id=asset_id or None))


def cancel_all() -> dict:
    return _dump(_with_backoff(get_clob_client().cancel_all))


def get_open_orders(asset_id: str | None = None) -> list[dict]:
    kwargs = {"token_id": asset_id} if asset_id else {}
    try:
        resp = _with_backoff(get_clob_client().list_open_orders, **kwargs)
    except TypeError:
        resp = _with_backoff(get_clob_client().list_open_orders)
    items = list(resp or [])
    return [_dump(o) for o in items]


def get_order(order_id: str) -> dict:
    return _dump(_with_backoff(get_clob_client().get_order, order_id=order_id))


def get_trades(**kwargs) -> list[dict]:
    resp = _with_backoff(get_clob_client().list_trades, **kwargs)
    return [_dump(t) for t in (resp or [])]


def get_collateral_balance() -> dict:
    """Wallet collateral balance/allowances at the CLOB (base units)."""
    client = get_clob_client()
    try:
        resp = client.get_balance_allowance(asset_type="COLLATERAL")
    except Exception:
        from polymarket.types import AssetType  # enum fallback
        resp = client.get_balance_allowance(asset_type=AssetType.COLLATERAL)
    return _dump(resp)
