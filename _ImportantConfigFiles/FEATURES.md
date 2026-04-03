# PolyMarket Bot — Feature Reference

## Engine Core
- **Trading Engine**: APScheduler loop, configurable interval (default 5min)
- **Module Auto-Discovery**: Drop package in `api/modules/`, engine finds it
- **Paper/Live Mode**: Toggle simulated vs real USDC trading
- **Shadow Mode**: Paper trades alongside live for comparison
- **Circuit Breaker**: Auto-halt after N consecutive losses, cooldown

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

## Historical Data Scripts
- `scripts/import_cnn_archive.py` — CNN archive → hourly/daily/weekly + stats
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
