"""Copy Trading signal builder.

Converts a decided BUY/SELL copy into a `Signal` object the existing
PaperExecutor / LiveExecutor + risk_manager can consume. We never bypass
the standard 15-check pipeline.

Limit orders only. BUY uses the whale's fill price (capped at current ask).
SELL uses the current best_bid for predictable fill, never a market order.
"""
from __future__ import annotations

from api.services.risk_manager import Signal


def build_buy_signal(
    *, module_id: str, market_id: str, token_id: str | None, bracket: str | None,
    whale_price: float, current_best_bid: float, current_best_ask: float,
    size_usd: float, our_bankroll: float, wallet_id: str, wallet_address: str,
    whale_trade_id: str, event_slug: str | None = None, shadow_mode: bool = True,
) -> Signal:
    """Build a BUY Signal mirroring a whale trade.

    Price: we want to fill at the whale's price or better. If the current
    ask is below the whale's fill, we take it (better than the whale got).
    If the ask is higher, we wait at the whale's price as a resting limit.
    """
    if current_best_ask > 0 and whale_price > current_best_ask:
        limit_price = current_best_ask
    else:
        limit_price = whale_price if whale_price > 0 else current_best_ask
    if limit_price <= 0:
        limit_price = current_best_bid or 0.01

    kelly_pct = (size_usd / our_bankroll) if our_bankroll > 0 else 0.0
    return Signal(
        module_id=module_id,
        market_id=market_id,
        bracket=bracket or "",
        side="BUY",
        edge=0.0,
        model_prob=0.0,
        market_price=limit_price,
        kelly_pct=kelly_pct,
        confidence=0.5,
        best_bid=current_best_bid,
        best_ask=current_best_ask,
        token_id=token_id,
        metadata={
            "strategy": "copy_trading",
            "signal_type": "copy",
            "copy_source_wallet": wallet_address,
            "copy_wallet_id": wallet_id,
            "whale_trade_id": whale_trade_id,
            "whale_price": whale_price,
            "target_size_usd": size_usd,
            "shadow_mode": shadow_mode,
            "skip_edge_check": True,
            "event_slug": event_slug,
        },
    )


def build_sell_signal(
    *, module_id: str, market_id: str, token_id: str | None, bracket: str | None,
    sell_fraction: float, current_best_bid: float, current_best_ask: float,
    wallet_id: str, wallet_address: str, whale_trade_id: str,
    position_id: str | None = None, event_slug: str | None = None,
    shadow_mode: bool = True,
) -> Signal:
    """Build a SELL Signal mirroring a whale exit.

    sell_fraction is [0, 1]. Routed via kelly_pct so PaperExecutor /
    LiveExecutor interpret it as "fraction of existing position to liquidate".
    Limit price = current best_bid (predictable fill, never market).
    """
    limit_price = current_best_bid if current_best_bid > 0 else 0.01
    return Signal(
        module_id=module_id,
        market_id=market_id,
        bracket=bracket or "",
        side="SELL",
        edge=0.0,
        model_prob=0.0,
        market_price=limit_price,
        kelly_pct=max(0.0, min(1.0, sell_fraction)),
        confidence=1.0,
        best_bid=current_best_bid,
        best_ask=current_best_ask,
        token_id=token_id,
        metadata={
            "strategy": "copy_trading",
            "signal_type": "copy",
            "copy_source_wallet": wallet_address,
            "copy_wallet_id": wallet_id,
            "whale_trade_id": whale_trade_id,
            "sell_fraction": sell_fraction,
            "position_id": position_id,
            "shadow_mode": shadow_mode,
            "skip_edge_check": True,
            "force_exit": True,
            "event_slug": event_slug,
        },
    )
