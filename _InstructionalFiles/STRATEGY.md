# PolyMarket Bot — Trading Strategies

## Module Architecture
- Drop a Python package in `api/modules/` -> engine auto-discovers it
- Each module extends `BaseModule` ABC from `api/modules/base.py`
- Required methods: `evaluate() -> list[Signal]`
- Config stored in `settings` table as JSONB, loaded per cycle

## Active Modules

### 1. Truth Social Posts (`api/modules/truth_social/`)
- **Market**: Weekly Trump post count brackets (0-19 through 200+)
- **Ensemble**: 5-model pacing + optional parquet (6 total)
- **Data**: xTracker, Gamma, Google News RSS (4 queries), LunarCrush, Presidential Schedule
- **AI**: Claude Haiku regime override (1 call/cycle)
- **Regime**: Z-score + Claude news override (SURGE/HIGH/NORMAL/LOW/QUIET/TRANSITION)
- **Sizing**: Fractional Kelly (0.25x), volatility damping, time decay
- **Weights**: Percentage-based (works for any auction length), calibration-adjusted

### 2. Elon Musk Tweets (`api/modules/elon_tweets/`)
- **Market**: Weekly/monthly Elon tweet count brackets (dynamic from Gamma)
- **Ensemble**: 5-model pacing + LunarCrush + Hawkes + Claude regime override
- **Data**: xTracker, Gamma, Google News RSS (4 queries), LunarCrush, Schedule
- **Supports**: Variable auction periods (7-day, 14-day, 30-day)

## 5-Model Pacing Ensemble
| Model | File | What It Does |
|-------|------|-------------|
| Linear Pace | pacing.py | Simple extrapolation: (posts/elapsed) x total |
| Bayesian | pacing.py | Blends historical prior with observed pace |
| DOW-Hourly | pacing.py | Projects remaining hours using DOW + hour patterns |
| Historical | enhanced_pacing.py | Recency-weighted 12-week average (half-life=4d) |
| Hawkes | hawkes.py | Self-exciting burst model for reply storms |

## Ensemble Weight Strategy
```
Early (<25%):  pace=low, bayesian=high, dow=med, historical=high, hawkes=regime
Mid (25-75%):  pace=med, bayesian=high, dow=med, historical=low,  hawkes=regime
Late (>75%):   pace=high, bayesian=med,  dow=low, historical=min, hawkes=regime
Hawkes: 15% in SURGE/HIGH regimes, 8% in NORMAL/LOW
+ Calibration adjustment: +/-20% based on per-model Brier scores
+ Parquet model: 20% when available (scales others proportionally)
```

## Signal Modifier Stack (Trump)
| Source | Weight | What It Provides |
|--------|--------|-----------------|
| Google News RSS | 40% | 4 queries, conflict keywords, schedule events |
| LunarCrush | 25% | Engagement velocity, social dominance |
| Factbase Schedule | 20% | Rally/court/travel/golf modifiers (WH Press Office) |
| Google Trends | 15% | "Trump Truth Social" interest momentum |

## Signal Modifier Stack (Elon)
| Source | Weight | What It Provides |
|--------|--------|-----------------|
| Google News RSS | 60% | 4 queries, conflict keywords, schedule events |
| LunarCrush | 40% | Engagement velocity, social dominance |

## Risk Checks (15 Pre-Trade Gates)
1. Circuit breaker  2. Edge threshold (2%)  3. Kelly validation
4. Position cap (15%)  5. Daily loss (5%)  6. Weekly loss (10%)
7. Max drawdown (15%)  8. Portfolio exposure (50%)  9. Single market (15%)
10. Correlated exposure (30%)  11. Duplicate prevention  12. Cross-module correlation
13. Settlement decay  14. Spread check  15. Liquidity check

## Order Execution Rules (NON-NEGOTIABLE)
- **ALWAYS limit orders** — NEVER market orders. Every order MUST specify a `price`.
- Market orders have unbounded slippage on Polymarket's thin order books.
- Limit price = CLOB midpoint (preferred) or Gamma price (fallback).
- If spread exceeds threshold, do NOT place the order.

## Future Enhancements
- **X API v2** (or 3rd-party scraper): Sub-second tweet detection for Elon module
- **Resolution rule counter**: Shadow xTracker counting methodology for edge
- **Kalman Filter**: Adaptive noise filtering for noisy count data
- **Reddit API**: r/politics + r/elonmusk targeted monitoring (if LunarCrush insufficient)
- **Per-bracket order book fetch**: Enable full contrarian + depth sizing
- **Staging environment**: Railway preview deploy with paper mode for pre-prod testing
- **Test suite**: Unit tests for signals, pacing, risk; integration tests for order lifecycle
- **Backtest framework**: Historical replay against resolved auctions
- **Max daily loss kill switch**: Auto-halt if cumulative daily loss exceeds threshold
- **Deployment freeze flag**: ENV var to block deploys during high-volatility events
