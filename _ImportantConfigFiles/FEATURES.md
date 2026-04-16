# PolyMarket Bot — Feature Reference

## Engine Core
- **Trading Engine**: APScheduler loop, configurable interval (default 5min)
- **Module Auto-Discovery**: Drop package in `api/modules/`, engine finds it
- **Paper/Live Mode**: Toggle simulated vs real USDC trading
- **Shadow Mode**: Paper trades alongside live for comparison
- **Circuit Breaker**: Auto-halt after N consecutive losses, cooldown
- **Auto-Kill Switch**: Pause module after N consecutive losses (default 5, togglable)
- **Price Floor**: Reject paper trades with market_price < 0.01 (1¢)
- **Liquidity Check**: Paper fills at actual best ask/bid, capped at available depth

## Trump Module (Full Feature Set)
- **5-Model Ensemble**: Linear Pace, Bayesian, DOW-Hourly, Historical, Hawkes
- **Calibration-driven weights**: Auto-adjusts from Brier scores (+/-20%)
- **Cross-bracket normalization**: Probabilities sum to 1.0
- **Regime detection**: Z-score + Claude Haiku AI override
- **Signal modifier**: News(40%) + LunarCrush(25%) + Schedule(20%) + Trends(15%)
- **4 schedule sources**: factba.se + WhiteHouse.gov + FEC + news fallback
- **CNN archive verification**: Cross-references xTracker counts with CNN
- **Cross-bracket arbitrage**: Detects probability mass misallocations
- **Contrarian signals**: Fades overcrowded brackets by volume
- **Historical hourly patterns**: Cross-week averages from CNN archive import
- **Full signal metadata**: All context data stored for dashboard review

## Elon Module (Full Feature Set)
- Same 5-model ensemble, LunarCrush, Hawkes, Claude regime override
- Signal modifier: News(60%) + LunarCrush(40%) (no schedule)
- Variable auction periods (7/14/30 day)
- Dynamic bracket detection from Gamma API

## Data Sources (10 Active)
| Source | Purpose | Modules |
|--------|---------|---------|
| xTracker | Post counts + tracking periods | Both |
| CNN Archive | Truth Social count verification + historical hourly data | Trump |
| Gamma API | Prices, brackets, volume | Both |
| CLOB API | Order book + execution | Both |
| Google News RSS | 4 targeted queries per handle (deduped) | Both |
| LunarCrush | Engagement velocity + social dominance | Both |
| Claude Haiku | News regime classification (1 call/cycle) | Both |
| Factbase | Presidential schedule (WH Press Office + pool reports) | Trump |
| factba.se | Historical presidential schedule | Trump |
| Google Trends | Interest-over-time momentum | Trump |
| Polymarket Parquet | Historical price data | Both |

## Truth Social Module Dashboard
- **DOW Averages Heatmap**: 7-day grid, recency-weighted, green intensity scale
- **Hourly Posts Clock**: SVG clock face with 24-hour posts/hr (4yr historical data)
- **Daily Pacing Table**: Day-by-day actual vs expected, deviation, status indicators
- **Pace Acceleration**: Current vs prior posting rate with momentum label
- **Confidence Bands**: Top 3 projected brackets with probability bars
- **Ensemble Breakdown**: 4-model projections with weights and contributions
- **Bid Prices by Day & Hour**: 7x24 heatmap from `price_snapshots` (green=cheap)
- **Bid Prices by Days Since Launch**: Bracket price evolution over auction lifecycle
- **Positions Table**: AVG->NOW prices, current market value, unrealized P&L
- **Auction Selector**: Dropdown with Active/Past groups (replaced horizontal tabs)
- **Current Value Card**: Shows market value (not cost basis) with unrealized P&L
- **Module P&L Chart**: Cumulative P&L area chart with return %, max drawdown, trade count
- **Bankroll Card**: Editable % of account, derived dollar amount
- **Bracket Cap Card**: Editable % of bankroll, derived dollar amount
- **Pacing Chart**: Actual vs expected vs projected lines (inside pacing table card)
- **Layout System**: 3 standard widths (full/half/third) via CSS grid

## Historical Data Pipeline
- **Post data**: CNN archive (32K+ posts, 2022-02 to present, hourly granularity)
- **Price data**: CLOB API `/prices-history` backfill (23K+ snapshots, all 17 auctions)
- **Ongoing collection**: Hourly price snapshots via `snapshots.py` scheduler
- **Supabase table**: `price_snapshots` (dow, hour_of_day, elapsed_days, tracking_id)

## Historical Data Scripts
- `scripts/import_cnn_archive.py` — CNN archive -> hourly/daily/weekly + stats
- `scripts/backfill_prices.py` — CLOB API -> price_snapshots for all past auctions
- `scripts/fetch_historical_auctions.py` — all past xTracker auctions
- `scripts/import_historical.py` — generic CSV/JSON importer

## Frontend (9 Pages)
Dashboard | Modules | Portfolio | Trades | Backtest | Analytics | Notes | Logs | Settings

## Notes Page (7 Tabs)
- **Setup Notes**: Env vars, dependencies, migrations, weight references
- **Trump Module**: Schedule impacts, data sources, regime logic, count verification
- **Elon Module**: Key differences, signal weights, burst patterns
- **How It Works**: Full 10-step pipeline in layman's terms
- **Data Sources**: All active integrations with latency + module mapping
- **Risk Rules**: 15 pre-trade checks explained
- **Changelog**: Session-by-session feature history

## Risk Manager (15 Checks)
Circuit breaker, edge (2%), Kelly, position cap (15%), daily (5%),
weekly (10%), drawdown (15%), portfolio (50%), single market (15%),
correlated (30%), duplicate, cross-module, settlement decay, spread, liquidity

## Order Execution
- **Limit orders ONLY** — market orders are prohibited project-wide
- Every order must specify a `price` parameter (CLOB midpoint preferred)
- ENV guard required for live execution (PAPER_MODE check)

## Claude Code Tooling (.claude/)
### Agents (7)
| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `@qa-reviewer` | Bugs, edge cases, security | After code changes, before commit |
| `@verify-bot` | End-to-end paper mode verification | Before PRs on trading code |
| `@strategy-reviewer` | Validate against strategy rules | Before committing signal/pacing changes |
| `@api-integrator` | API endpoint integration | Adding new data sources or endpoints |
| `@doc-updater` | Auto-update docs from git diff | After feature completion or session end |
| `@module-scaffolder` | New module package creation | When adding new trading modules |
| `@risk-auditor` | Audit all money-touching code | Before going live |

### Skills (2)
- `polymarket-api` — API rules, rate limits, endpoint reference
- `betting-strategy` — Kelly, ensemble weights, risk rules

### Commands (3)
- `/pre-commit` — Chain QA + strategy + risk + verify
- `/check-status` — Project status overview
- `/post-session` — End-of-session doc updates
