# PolyMarket Bot — Feature Reference

## Engine Core
- **Trading Engine**: APScheduler loop, configurable interval (default 5min)
- **Module Auto-Discovery**: Drop package in `api/modules/`, engine finds it
- **Paper/Live Mode**: Toggle simulated vs real USDC trading
- **Shadow Mode**: Paper trades alongside live for comparison
- **Circuit Breaker**: Auto-halt after N consecutive losses, cooldown
- **Auto-Kill Switch**: Pause module after N consecutive losses (default 5, togglable)
- **Price Floor**: Reject paper trades with market_price < 0.001 (0.1¢ tick floor)
- **Tick-snap at emit** (2026-05-18): truth_social rounds market_price to bracket's min_tick_size before signal build, eliminates `below_min_tick_size` rejection
- **Thin-book BUY bypass** (2026-05-18): risk_manager._check_spread lets cheap-lottery BUYs (<10¢) through when Gamma returns null bid (lottery thesis = buy thin, hold to resolution)
- **Liquidity Check**: Paper fills at actual best ask/bid, capped at available depth

## Observability
- **HealthBadge** (2026-05-18): runtime "is this module actually working" badge on every module card + detail page. States: 🟢 Trading (fills <24h) / 🟡 Cycling (cycling but 0 fills, shows reason) / 🔴 Stuck (errors or no heartbeat). Computed server-side via `/api/modules/{id}/realtime-health` — 3 small Supabase reads per module
- **Daily QA agent** (2026-05-18): scheduled task runs every 9 AM ET, 8 health checks, notifies Sir only on failure. Free under Claude Code subscription. Task file at `~/.claude/scheduled-tasks/polymarket-bot-daily-qa/`

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

## Copy Trading Module (Phase 1 — paper, 2026-05-13)
- Mirrors whale-wallet trades polled from `data-api.polymarket.com/trades` (default 30s)
- 4 hard caps: per-wallet exposure, per-trade size, daily-loss circuit, whale-perf gate
- Staleness/drift gates + `(wallet_id, whale_trade_id)` dedupe; cold-start drop of stale trades
- Wallet-scoped cost-basis (`copy_source_wallet`) for per-wallet P&L attribution
- Tables: `copy_trade_wallets`, `copy_trade_state`, `copy_trade_log`; paper via `shadow_mode=true`

## Data Sources (10 Active)
| Source | Purpose | Modules |
|--------|---------|---------|
| xTracker | Post counts + tracking periods | Both |
| Truth Social Direct | Independent post-count verification via Mastodon-compatible API | Trump |
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

## Parquet History Tooling (added 2026-05-05)
**Streamed full Polymarket history (3.5y, 766M trades, 1M markets) via DuckDB+HuggingFace.**
- `_DataMetricPulls/duckdb_remote.py` — connection helper exposing `markets`/`quant`/`trades` SQL views over remote Parquet
- `_DataMetricPulls/full_history_analysis.py` — strict-recurring classification + flip-pattern ranking
- `_DataMetricPulls/duckdb_cache/polymarket_remote.duckdb` — persistent cache of materialized aggregations
- HF token at `~/.credentials/shared.env` (`HF_TOKEN=hf_…`)
- **Use this for**: cross-market backtesting, longer-than-3-month historical context, strategy calibration
- **vs LuciferForge $9 SQLite**: 96× more time, 94× more trades, $0 cost

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
### Agents (9)
| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `@qa-code-bug-hunter` | Runtime bugs, edge cases, security, performance, trading-specific risks | After code changes, before commit (chained in /pre-commit) |
| `@qa-code-quality` | Orphan code, dupes, hotfix layering, bloat, bad abstractions | Weekly or before major refactors — NOT per-PR |
| `@qa-architecture-quality` | Module boundaries, abstraction leaks, dependency direction, convention compliance | Monthly or before adding new module — NOT per-PR |
| `@verify-bot` | End-to-end paper mode verification | Before PRs on trading code |
| `@strategy-reviewer` | Validate against strategy rules | Before committing signal/pacing changes |
| `@api-integrator` | API endpoint integration | Adding new data sources or endpoints |
| `@doc-updater` | Auto-update docs from git diff | After feature completion or session end |
| `@module-scaffolder` | New module package creation | When adding new trading modules |
| `@risk-auditor` | Audit all money-touching code | Before going live |

### External code-quality tooling
- **SonarCloud** — runs on every PR via GitHub Action. Free for public repos. Catches cyclomatic complexity, real bugs, dead code, security smells. Findings appear as PR comments.

### Skills (2)
- `polymarket-api` — API rules, rate limits, endpoint reference
- `betting-strategy` — Kelly, ensemble weights, risk rules

### Commands (3)
- `/pre-commit` — Chain QA + strategy + risk + verify
- `/check-status` — Project status overview
- `/post-session` — End-of-session doc updates

## Future Items (Backlog)

### Strategy A/B testing via per-module separation
- Goal: run two strategies side-by-side on the same auction with isolated bankrolls; compare P&L, win rate, Brier score
- Approach: second module extending `BaseModule` with its own row in `modules` table and fixed-$ bankroll; reuses shared infra
- Prereqs: PR #9 snapshots verified live; Strategy 2 logic specced before scaffolding

### Future strategy tests (deferred during PR 1-5 strategy upgrade)
- **Sell winners when pacing turns against** — backtest historically lost money on this rule (capped upside on real winners). Worth re-testing now that the ensemble has running_total floor + variance shrinkage. Build as a togglable exit rule (`sell_on_pacing_reversal`, default OFF).
- **Manual buy/sell UI in dashboard** — currently user trades directly on Polymarket. Adding a manual buy panel + sell button per open position lets the user act on divergence alerts without leaving the dashboard. Requires: `POST /api/orders/manual` route, dashboard form, and reuse of existing executor (paper/live based on env).
- **Polymarket position reconciliation job** — every cycle, pull actual Polymarket positions and reconcile against `positions` table. Makes the bot self-healing regardless of where the user trades. ~30 LOC, decoupled from the manual UI.
- **`buy_at_historical_low_regardless_of_edge` toggle** — Approach B from the Q5 spec: bypass the edge check entirely when current price is below the historical-low entry. Removed from PR 4 because it was unwired. Wire when needed.

### Pre-existing fixes deferred during PR 1-5
- **Move `rank_brackets()` to AFTER contrarian_signal adjustment** — flagged by @strategy-reviewer in PR 4. Currently `top_brackets_for_books` is computed before contrarian adjusts probabilities, so the top-N never reflects contrarian signals. Pre-existing bug, separate refactor. ~5 LOC change in `truth_social/module.py`.
- **Pre-auction order book quality** — flagged by @risk-auditor in PR 4. Pre-auction Polymarket markets often have wide one-sided spreads that bypass `_check_spread`'s sentinel. Before flipping `pre_auction_buying_enabled` to True, verify `slippage_tolerance` is tight (~0.05) and consider forcing `fetch_order_book(token_id)` (real CLOB) over Gamma's `bestBid`/`bestAsk` in that path.
- **`_check_negative_ev_aggregate` fail-open inconsistency** — sibling exposure checks fail-closed on DB error, this one fails-open. Align before live trading on real money.
