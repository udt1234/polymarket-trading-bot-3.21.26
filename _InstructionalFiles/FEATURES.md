# PolyMarket Bot — Feature Reference

## Engine Core
- **Trading Engine**: APScheduler loop, configurable interval (default 5min)
- **Module Auto-Discovery**: Drop a package in `api/modules/`, engine finds it automatically
- **Paper/Live Mode**: Toggle between simulated and real USDC trading
- **Shadow Mode**: Run paper trades alongside live for comparison
- **Circuit Breaker**: Auto-halt after N consecutive losses, configurable cooldown
- **Stale Data Detection**: Pauses trading if no signals generated in 2+ hours
- **Daily P&L Snapshots**: Cron at 23:55 UTC + hourly backup

## Risk Manager (15 Checks)
1. Circuit breaker (consecutive losses → cooldown)
2. Edge threshold (minimum edge to trade, default 2%)
3. Kelly validation (positive Kelly only)
4. Position size cap (15% max per market)
5. Daily loss limit (5% of bankroll)
6. Weekly loss limit (10% of bankroll)
7. Max drawdown (15% peak-to-valley)
8. Portfolio exposure limit (50% total)
9. Single market exposure limit (15%)
10. Correlated exposure limit (30% in similar brackets)
11. Duplicate trade prevention (requires 3%+ edge improvement)
12. Cross-module correlation (2+ modules in same direction)
13. Settlement decay (reduce/reject near resolution)
14. Spread check (slippage tolerance)
15. Liquidity check (order book depth)

## Modules

### Truth Social Posts
- **4-Model Ensemble**: Linear Pace, Bayesian Prior, DOW-Hourly, Historical Avg
- **Dynamic ensemble weights**: Early week trusts history, late week trusts pace
- **Regime detection**: Z-score based (HIGH/SURGE/NORMAL/QUIET/LOW/TRANSITION)
- **Signal modifier**: News intensity + conflict score + schedule events
- **Smart bracket targeting**: Only trades top 3 brackets by edge×liquidity×confidence
- **Time-weighted Kelly**: Reduces sizing late in auction period
- **Recency-weighted DOW averages**: Exponential decay (half-life configurable)
- **Regime-conditional averages**: Separate DOW stats for HIGH vs NORMAL regimes
- **Variance tracking**: Per-DOW and per-hour standard deviations
- **Deviation tracker**: Real-time comparison vs expected DOW pace
- **Pace acceleration**: Momentum detection (today vs yesterday rate)
- **Historical periods toggle**: Configurable lookback (default 9, auto-optimizable)
- **Confidence bands**: Shows probability distribution across top brackets
- **Optimal entry timing**: Best historical hour/day to enter each bracket

### Elon Musk Tweets
- Shares pacing/projection/regime/signals code with Truth Social
- Auto-discovers market slug from xTracker
- Dynamic bracket detection from Gamma API
- Supports both weekly and monthly auction periods

## Wallet & Profiles
- **Multi-profile support**: Store multiple Polymarket wallets with API keys
- **One-click profile switching**: Change active wallet from Settings
- **Multi-account execution**: Toggle per-profile, broadcasts same trades to all
- **Live wallet data**: Portfolio value, positions, trades from Polymarket Data API
- **Auction grouping**: Dashboard groups positions by market with accordion detail

## Analytics (13 Endpoints)
- Sharpe, Sortino, Calmar, Profit Factor ratios
- ROI by timeframe (daily/weekly/monthly/all-time)
- Drawdown chart with max drawdown tracking
- Edge decay trend (decaying/stable/improving)
- Fill rate and average slippage
- Bracket heatmap (win rate, P&L, edge per bracket)
- Regime indicator with z-score
- Correlation matrix (position concentration, HHI index)
- Walk-forward validation health
- P&L attribution (by module, bracket, strategy)
- Monte Carlo simulation (1000 paths, percentile curves)
- Alert history (risk events, circuit breaker trips)
- Calibration log (Brier score, predicted vs actual)

## Accuracy & Resolution
- **Auto-resolution tracking**: Detects resolved markets, closes positions
- **Calibration scoring**: Brier score + log loss per prediction
- **Accuracy trend**: Weekly Brier scores over 12 weeks
- **Walk-forward validation**: Every 6h, auto-reduces Kelly if model drifts

## Backtest Framework
- **Market search**: Query Polymarket events via Gamma API
- **Strategy replay**: Mean reversion, momentum, ensemble strategies
- **Parquet data loader**: Download historical price data from Polymarket S3
- **Results storage**: Saves backtests to Supabase with equity curves
- **UI page**: Search → configure → run → view results with charts

## Exit Strategy
- Take profit at 1.5x entry price
- Cut loss at 0.3x entry price
- Time decay after 5 days (reduce exposure)
- Edge reversal (model flips against position)

## Frontend
- **8 pages**: Dashboard, Modules, Portfolio, Trades, Backtest, Analytics, Logs, Settings
- **Login**: Supabase auth (email/password)
- **Dark mode default**, light mode toggle
- **Auto-refresh**: Dashboard metrics every 30s, engine status every 15s
- **Mobile**: Bottom tab bar on small screens
- **PWA**: Installable on iPhone home screen
- **CSV export**: Trades and wallet history
- **Live mode toggle**: Paper ↔ Live with confirmation dialog

## Integrations
- **Polymarket**: CLOB API (orders), Gamma API (markets), Data API (positions)
- **xTracker**: Post counts, tracking data for Truth Social + Elon
- **Supabase**: Auth, database (13 tables), RLS
- **LunarCrush**: Social sentiment modifier (optional, needs API key)
- **Slack**: Trade notifications, circuit breaker alerts (needs webhook URL)

## Data Sources
- **xTracker API**: Hourly post counts, tracking periods
- **Gamma API**: Market events, bracket prices, resolution status
- **CLOB API**: Order book, midpoints, order execution
- **Polymarket Data API**: Wallet positions, trade history
- **Polymarket Parquet (S3)**: Historical price data for backtesting
