"""Copy Trading data layer — polls Polymarket data-api for whale trades.

Uses primitives from api.services.wallet (fetch_wallet_trades,
fetch_wallet_balance, fetch_wallet_summary). Normalizes the raw /trades
response into a stable shape the decision layer can consume.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from api.services.wallet import fetch_wallet_trades, fetch_wallet_balance, fetch_wallet_summary

log = logging.getLogger(__name__)


def _to_dt(ts) -> datetime | None:
    """data-api /trades returns `timestamp` as unix seconds (int) on most
    endpoints. Some legacy fields use ISO strings. Accept both."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (ValueError, OSError):
                return None
    return None


def normalize_trade(raw: dict) -> dict | None:
    """Normalize one /trades row into the shape the decision layer expects.

    Returns None when the trade can't be parsed (skipped, logged upstream).
    """
    if not isinstance(raw, dict):
        return None
    side = str(raw.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        return None
    ts = _to_dt(raw.get("timestamp") or raw.get("t") or raw.get("createdAt"))
    if ts is None:
        return None
    # whale_trade_id: prefer transactionHash (stable, on-chain). Fall back to
    # a composite if missing. The (wallet_id, whale_trade_id) UNIQUE index
    # on copy_trade_log handles dedupe either way.
    trade_id = (
        raw.get("transactionHash")
        or raw.get("hash")
        or raw.get("id")
        or f"{raw.get('asset', '')}:{raw.get('side', '')}:{raw.get('price', '')}:{raw.get('size', '')}:{raw.get('timestamp', '')}"
    )
    try:
        price = float(raw.get("price", 0) or 0)
        size = float(raw.get("size", 0) or 0)
    except (TypeError, ValueError):
        return None
    return {
        "whale_trade_id": str(trade_id),
        "timestamp": ts,
        "side": side,
        "price": price,
        "size": size,
        "asset": raw.get("asset") or raw.get("tokenId") or "",
        "condition_id": raw.get("conditionId") or raw.get("condition_id") or "",
        "outcome": raw.get("outcome") or "",
        "title": raw.get("title") or "",
        "event_slug": raw.get("eventSlug") or raw.get("slug") or "",
        "market_id": raw.get("conditionId") or raw.get("condition_id") or raw.get("market") or "",
    }


async def poll_wallet_trades(wallet_address: str, limit: int = 50) -> list[dict]:
    """Fetch the latest /trades for a wallet, normalized + newest-first."""
    raw_trades = await fetch_wallet_trades(wallet_address, limit=limit)
    out: list[dict] = []
    for raw in raw_trades or []:
        norm = normalize_trade(raw)
        if norm is not None:
            out.append(norm)
    out.sort(key=lambda t: t["timestamp"], reverse=True)
    return out


async def fetch_wallet_portfolio_value(wallet_address: str) -> float:
    """Best-effort portfolio value (cash + open positions). Used for the
    BUY-sizing math: whale_size_pct = whale_trade_$ / portfolio_value."""
    try:
        summary = await fetch_wallet_summary(wallet_address)
        return float(summary.get("portfolio_value", 0) or 0)
    except Exception as e:
        log.warning(f"fetch_wallet_portfolio_value({wallet_address}) failed: {e}")
        try:
            return float(await fetch_wallet_balance(wallet_address))
        except Exception:
            return 0.0
