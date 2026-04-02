# Risk Management Rules

## 15 Pre-Trade Checks (ALL must pass)

| # | Check | Threshold | Action on Fail |
|---|-------|-----------|----------------|
| 1 | Circuit breaker | N consecutive losses | Halt ALL trading, cooldown |
| 2 | Edge threshold | < 2% | PASS (no trade) |
| 3 | Kelly validation | Negative or NaN | Reject signal |
| 4 | Position cap | > 15% per bracket | Reduce size to 15% |
| 5 | Daily loss | > 5% of portfolio | Halt for day |
| 6 | Weekly loss | > 10% of portfolio | Halt for week |
| 7 | Max drawdown | > 15% from peak | Halt, require manual restart |
| 8 | Portfolio exposure | > 50% deployed | No new positions |
| 9 | Single market | > 15% in one market | Reduce or skip |
| 10 | Correlated exposure | > 30% in correlated markets | Skip |
| 11 | Duplicate prevention | Same bracket + same auction | Skip |
| 12 | Cross-module correlation | Overlapping bets across modules | Reduce |
| 13 | Settlement decay | < 2 hours to settlement | No new positions |
| 14 | Spread check | Bid-ask > threshold | Skip |
| 15 | Liquidity check | Order book depth < minimum | Skip |

## Loss Limit Cascade
1. Daily loss hit → pause new orders, keep existing
2. Weekly loss hit → close non-essential, pause all new
3. Max drawdown hit → close all, halt engine, require manual restart

## Position Sizing Formula
```
edge = model_prob - market_price
odds = (1 - market_price) / market_price
full_kelly = model_prob - (1 - model_prob) / odds
sized = full_kelly * kelly_fraction * confidence_adj * (1 - settlement_decay)
final = min(sized, position_cap, remaining_portfolio_budget)
```

## Critical: Order Type
ALL orders MUST be limit orders. The `price` parameter is REQUIRED.
Market orders have unbounded slippage on Polymarket's order book.
