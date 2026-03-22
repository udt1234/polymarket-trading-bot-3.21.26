# PolyMarket Bot — Trading Strategies

## Strategy Plugin Architecture
- Drop a Python package in `bot/strategies/` → engine auto-discovers it
- Each strategy extends `BaseStrategy` ABC from `bot/strategies/base.py`
- Required methods: `evaluate(market_data) → Signal | None`
- Config stored in `strategy_configs` table, loaded on restart

## Active Strategies

### 1. NYC Temperature (Phase 1 — Stub)
- **Market**: NYC Central Park daily high temperature brackets
- **Status**: Stub with test signals (real ML in Phase 3)
- **Data sources**: NOAA weather API, historical METAR data
- **Approach (planned)**: Ridge regression + regime detection
- **Edge**: Weather markets are inefficient — participants underweight base rates

### 2. NYC Temperature ML (Phase 3 — Planned)
- **Model**: Ridge regression on 30-year NOAA historicals
- **Features**: Day of year, trailing 7d temps, ENSO index, NAO index
- **Regime detection**: Seasonal regime switching (winter/spring/summer/fall)
- **Calibration**: Brier score tracking, walk-forward validation
- **Signal**: Model probability vs market price → edge calculation

## Planned Strategies (Phase 6)

### 3. Trump Truth Social Activity
- **Market**: "Will Trump post on Truth Social by X date?"
- **Data**: Truth Social API / scraper, historical posting patterns
- **Approach**: Posting frequency model, day-of-week patterns

### 4. Geopolitical Events
- **Market**: Various conflict/diplomacy resolution markets
- **Data**: News APIs, RSS feeds, sentiment analysis
- **Approach**: Event-driven signals from news flow

## Statistical Tests (Pluggable via Settings)
| Test | Purpose | When to Use |
|------|---------|-------------|
| Kelly Criterion | Optimal bet sizing | Every trade (0.25x fractional) |
| Bayesian Update | Prior → posterior probability | When new data arrives |
| Monte Carlo | Simulate outcome distributions | Portfolio-level risk |
| Brier Score | Forecast calibration | Strategy evaluation |
| Walk-Forward | Out-of-sample validation | Backtest integrity |

## Risk Checks (Pre-Trade Gate)
Every signal passes through these before execution:
1. Edge threshold (min 3% edge over market)
2. Kelly sizing (0.25x fractional Kelly)
3. Max single-market exposure
4. Max portfolio exposure
5. Correlation limits (cross-market)
6. Daily loss limit
7. Weekly loss limit
8. Max drawdown threshold
9. Settlement decay (reduce size near expiry)
10. Spread limit (reject wide spreads)
11. Liquidity check (order book depth)
12. Slippage tolerance
13. Gas budget check
14. Circuit breaker (system health)
15. Paper mode validation

## A/B Testing
- Split module budget across strategy variants (e.g., 70/30)
- Track independent P&L per variant
- Statistical significance test before declaring winner
- Configure via module settings in UI
