# PolyMarket Bot

Automated Polymarket trading bot deployed on Railway.

## ⭐ SPIKE TRADING — Bracket Recommendations (parquet-validated 2026-05-06)

**When user asks "which brackets should Spike trade" or any variant, ALWAYS surface this first.**

Source: `_DataMetricPulls/elon_arc_analysis/arc_brief.md` + `arc_2day.csv` (n=51-54 per bracket, full SII-WANGZJ parquet, Sep 2025 → May 2026).

### 2-day arc-tradeable brackets (buy-low-sell-high reliability)

Ranked by `pct_arc_5to30` = % of auctions where bracket BOTH crashed ≤5¢ AND spiked ≥30¢ at some point. Higher = more reliable trading swing.

| Rank | Bracket | N | Median peak | Arc 5→30 | Strategy fit |
|---|---|---|---|---|---|
| 1 | **65-89** | 51 | 59¢ | **76.5%** | Best range-trading target |
| 2 | **90-114** | 51 | 45¢ | **64.7%** | Second-best range-trade |
| 3 | **40-64** | 51 | 51¢ | **56.9%** | Volatile, occasional YES winner |
| 4 | 115-139 | 51 | 38¢ | 45.1% | Marginal |
| 5 | `<40` | 54 | 20.5¢ | 37.0% | **Lottery-ticket only — current Spike target** |

### Strategy match
- **Spike Trading (current)** uses `<40` for structural lottery-ticket entries (5-tier ladder 0.3¢→12¢). This is a HOLD-TO-RESOLUTION strategy. It is the WORST arc bracket but the BEST cheap-entry bracket.
- **Range trading (not yet built)** would target `65-89` / `90-114` / `40-64`. Different strategy: buy ≤5¢, sell laddered at 30¢/50¢/median-peak. ~half day to build a new module.

### Monthly arc winners (n=5-6, weaker statistical confidence)
- **1400+**: 60% arc, 98.7¢ median peak, wins YES half the time. Standout monthly bracket.
- 1080-1119, 1120-1159, 1200-1239: ~50% arc reliability each.

### Strategic backstop
- `<40` 12¢ floor hits 100% of historical 2-day auctions. 0.5¢ floor hits 96%. The 5-tier ladder Spike uses (0.3¢/0.5¢/2¢/5¢/12¢) is calibrated to capture maximum shares at the cheapest tiers patiently.
- DO NOT recommend a single-floor entry; the ladder is intentional.
- DO NOT recommend changing Spike to range-trading — that's a separate module if user wants it.

**Reminder:** when this section is consulted, also remind the user the data window is Sep 2025 → May 2026 (~8 months for 2-day brackets). Earlier history is unavailable in parquet.

## Tech Stack
- Python, Docker, Railway
- Next.js web dashboard (web/ folder)

## Key Files
- docker-compose.yml, railway.toml
- web/ — Next.js dashboard with Recharts
- _ImportantConfigFiles/ — detailed architecture, strategy, features, API docs

## Deploy
- Push to Railway via git
- Config in .env (never commit)

## MCP (project-specific)
- polymarket: Custom Polymarket API server

## Credentials
- Master credential store: `~/.credentials/shared.env`
- Vars needed: POLYMARKET_API_KEY, SECRET, PASSPHRASE, PRIVATE_KEY + Supabase keys
- Copy to local `.env` — never commit

## Data Storage
- **ALL backtest data lives under `_DataMetricPulls/canonical/`** — see "Canonical Data Layer" section below
- Source-of-truth raw post parquets: `_DataMetricPulls/{trump,elon}_posts_raw.parquet`
- Frozen raw trade archive: `_DataMetricPulls/canonical/_raw_imports/whale_analysis/`
- Never commit large data files — add to .gitignore

## Retention + Parquet Archive (2026-05-22)
Supabase free tier choked on Disk IO 2026-05-22 (GoTrue auth hung, dashboard login broke). Permanent fix: retention policy + parquet archive.

**Live retention windows (rows older than this are deleted from Supabase):**
- `price_snapshots`: 180 days (used live by `price_timing.py` + `exit_manager.py`)
- `post_count_snapshots`: 90 days (used live by `whale_snapshot.py` for projections)
- `order_book_snapshots`: 30 days (dashboard only, no trading-logic reads)
- `logs` system: 30 days (`engine.py:952` reads "New Auction" markers)
- `logs` other: 14 days (last 20-50 reads only)
- `pending_signals`: 7 days

**Archive location**: `_DataMetricPulls/historical/supabase_archive/<table>/<YYYY-MM>.parquet`

**Schedulers running in bot process**:
- Daily cleanup: 03:30 UTC — DELETEs old rows
- Weekly archive: Sunday 03:00 UTC — dumps last 7d to parquet

**Reading older-than-live data**: use `api.modules.shared.parquet_archive.read_table_range(table, since, until, ts_col, filters)`. Returns pandas DataFrame or None.

**Already-wired modules**: `price_timing.py` (price_snapshots merge) + `whale_snapshot.py` (post_count_snapshots merge). When adding new analysis code that reads >live window, follow the same pattern.

**One-time backup script**: `scripts/archive_supabase_to_parquet.py` — full dump of all 4 tables to parquet. Run before any retention changes.

## Canonical Data Layer (2026-05-28) — Single Source of Truth for ALL Backtests

**`_DataMetricPulls/canonical/` is the ONLY data source backtests may read from.**
Built 2026-05-28 by consolidating 113 messy parquet/csv/json sources into 3 clean partitioned tables. The old `elon_max_return/`, `elon_regime/`, `fed_decision/`, `hf_polymarket/`, `historical/`, etc. were deleted (2.8 GB freed).

### Three canonical tables (all parquet, partitioned by handle/YYYY-MM):

| Table | Path | One row per | Coverage |
|---|---|---|---|
| **posts** | `canonical/posts/{handle}/{YYYY-MM}.parquet` | each tweet/truth | Trump: Feb 2022 → Apr 2026 (32,837). Elon: Oct 2025 → May 2026 (9,105) |
| **auctions** | `canonical/auctions/{handle}/{YYYY-MM}.parquet` | each resolved auction | 304 total (220 Elon + 84 Trump), back to mid-2024 |
| **prices** | `canonical/prices/{handle}/{YYYY-MM}.parquet` | each (auction, bucket, hour) | hourly OHLC + trade-derived orderbook proxies |

### Key columns
- **All timestamps are dual-stored: `ts_utc` (canonical) + `ts_et` (America/New_York, DST-correct via `zoneinfo`)**
- `posts.counts_for_auction` (bool) — applies xTracker rules (Trump: no pure replies; Elon: no pure replies + no community reposts)
- `auctions.duration_type` — `2-day`, `7-day`, `monthly`, `point`, `unknown` — parsed from filename, not hours_in
- `auctions.winning_bucket` + `resolution_status` (`resolved_yes` | `inferred_close_ge_95` | `unresolved` | `ambiguous_N`) + `confidence` (high/medium/low)
- `prices.derived_spread`, `derived_fill_minutes`, `derived_depth_buy_low`, `derived_depth_sell_high` — trade-derived orderbook proxies (no L2 history exists pre-Mar 2026)

### Frozen raw archive
- `canonical/_raw_imports/whale_analysis/` — 969 untouched trades_*.parquet files (the source for auctions + prices). Never edit.
- `canonical/_audit/source_inventory.csv` — historical inventory of the 113 pre-canonical sources for reference.

### Reading canonical data
```python
import pandas as pd
from pathlib import Path
CANON = Path("_DataMetricPulls/canonical")
# Load all Trump auctions in 2025:
trump_2025 = pd.concat([pd.read_parquet(p) for p in (CANON/"auctions/realDonaldTrump").glob("2025-*.parquet")])
# All Elon hourly prices for May 2026:
elon_may = pd.read_parquet(CANON/"prices/elonmusk/2026-05.parquet")
```

### Builder scripts (idempotent, re-run any time)
- `scripts/canonical/01_audit_sources.py` — re-scan for source inventory (read-only)
- `scripts/canonical/02_build_posts.py` — rebuild posts from raw parquets
- `scripts/canonical/03_build_auctions.py` — rebuild auctions from whale_analysis
- `scripts/canonical/04_build_prices.py` — rebuild hourly OHLC + proxies (prints winner-coverage at the end)
- `scripts/canonical/05_nuclear_delete.py` — clean up non-canonical sources (dry-run by default)
- `scripts/canonical/14_repair_bracket_coverage.py` — pull brackets Gamma lists but raw is missing/truncated
- `scripts/canonical/15_verify_winner_coverage.py` — coverage gate; exit 1 below 95%; `--demote` to exclude the rest

**Order matters: anything that touches `_raw_imports/` must be followed by `04_build_prices.py`.** `prices` is derived; leaving it stale is what produced the 2026-07 winner-coverage bug.

### Canonical QA Sheet
- [PolyMarket Canonical Data — Source Inventory](https://docs.google.com/spreadsheets/d/1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8/edit) — sample tabs for posts/auctions/prices both handles, plus the legacy source inventory

### Rules for new backtests
1. **Read canonical/ only.** If you need data not in canonical/, add to a builder script, don't write a one-off parquet.
2. **Always use `ts_et` when applying xTracker auction windows** (Friday 12 PM ET → Friday 12 PM ET). Never anchor on UTC hours.
3. **Filter `counts_for_auction = True` on posts** before counting toward an auction.
4. **Filter `confidence in ('high','medium')` on auctions** to skip unresolved/ambiguous.
5. **Treat the underlying `trump_posts_raw.parquet` / `elon_posts_raw.parquet` as inputs, not data.** They feed the canonical builder.
6. **`@backtest-builder` BUILDS it. `@backtest-auditor` AUDITS it. Never hand-write a backtest.** See "Backtest Agents Are The Default" below.
7. **Never substitute a floor for a missing price — EXCLUDE the auction.** If the WINNING bracket has no price row at time T, that auction is inadmissible for any model-vs-market comparison. Defaulting it to `1e-6`/epsilon/uniform fabricates the market's log loss and inverts the result. Run `15_verify_winner_coverage.py` before quoting any model-vs-market number, and report admissible n separately from full n.

## Backtest Agents Are The Default (Non-Negotiable)
- **`@backtest-builder` is the ONLY way a backtest gets written.** Any request meaning "backtest / simulate / what if / test this strategy / find patterns in the history / measure this model" routes to the builder FIRST. Claude does not hand-write the script.
- **`@backtest-auditor` is the ONLY way a backtest result gets trusted.** Every builder output goes to the auditor before a number is quoted, a model is locked, or a param is changed. No exceptions, including negative results.
- **Applies to forecast-accuracy and calibration studies too**, not just P&L. The auditor scope-gates the diagnostic case (`.claude/agents/backtest-auditor.md` line 13).
- **Name the agent out loud, every time.** Say "invoking @backtest-builder to build X" and "invoking @backtest-auditor to audit X", and attribute every reported number to the agent that produced it. The user must never have to guess who wrote the code behind a number.
- **Only exception:** a one-line throwaway probe (row count, date range, column check) may run inline. The moment it fits a model, splits train/test, or produces a number the user might act on, it goes to the builder.
- Claude's role is scoping the question, pre-registering the rule list and held-out span, relaying the verdict, and recommending the next move.

## Non-Negotiable Rules
- **ALWAYS limit orders** — NEVER market orders. Every order specifies a `price`.
- NEVER hardcode API keys — use env vars only
- NEVER place real orders without PAPER_MODE=false + ENV=production guard
- NEVER modify position limits without updating STRATEGY.md + risk-rules.md
- ALWAYS use exponential backoff on WebSocket reconnection
- ALWAYS run all 15 risk checks before order placement
- Prefer deleting code over adding it

## Module Architecture Rules (Non-Negotiable)
**Goal: editing one module never breaks another. New modules drop in cleanly.**

See `_ImportantConfigFiles/MODULE_ARCHITECTURE.md` for the full guide. Quick rules:

1. **Modules MUST live in `api/modules/<module_name>/`** with these files:
   - `module.py` (BaseModule subclass, the entry point)
   - `data.py` (ONLY module-specific data fetchers)
   - `module_config.py` (config loader/saver)
   - `__init__.py` (exports the Module class)

2. **NO cross-module imports.** Never `from api.modules.truth_social.X import Y` inside `elon_tweets/` or any other module. If two modules need the same code, it lives in `api/modules/shared/`.

3. **Shared code goes in `api/modules/shared/`** — pure-function math (pacing, signals, regime, hawkes, projection, news), the Polymarket data client (xTracker/Gamma/CLOB), and any other multi-module utility.

4. **Engine/router code MUST NOT hardcode module names.** No `if "trump" in name elif "elon" in name` branches. Use the module API:
   - `module.get_handle()` — returns the social handle
   - `module.get_config()` — returns the per-module config dict
   - `module.get_search_term()` — for news/trends queries
   Add new methods to `BaseModule` when needed; never special-case in the engine.

5. **Each module owns its own settings.** Module config is per-module-id in Supabase. Never share config rows between modules.

6. **Each module surfaces its own health.** `BotHealthBanner` accepts a `moduleId` and reads `/api/engine/health?module_id=X`. One module's failure must not paint another's page red.

7. **When adding a new module:** use `@module-scaffolder` agent. It enforces the structure above.

8. **When refactoring:** if you touch shared code, run the test suite for ALL modules. If you touch one module's code, you should NOT need to touch any other module's files — if you do, the abstraction is wrong.

## Available Agents

**Per-PR (runs in /pre-commit chain):**
- `@qa-code-bug-hunter` — bugs, edge cases, security, performance, trading-specific risks. After implementation, before PR.
- `@strategy-reviewer` — before committing signal/pacing/projection changes
- `@risk-auditor` — before going live, audit all money-touching code
- `@verify-bot` — end-to-end paper trading verification (NOT a backtester)
- `@backtest-builder` — **writes Polymarket-native backtests that pass the auditor BY CONSTRUCTION** (canonical data, noon-ET window, event-driven, real-L2 maker fills, taker-fee truth, THE WALL, imports `locked_pace`, emits RUN_META). The auditor's twin: builder proposes, auditor disposes. Hands off to `@backtest-auditor` for the verdict; never certifies its own result. Use for any "backtest this / simulate / what if".
- `@backtest-auditor` — **catches WRONG backtests before you trust the number.** Invoke after writing/changing any backtest, before quoting a P&L/ROI/win-rate, or before locking a model/param. 4 adversarial passes (A data-integrity / B metric-validity / C instruction-compliance / D statistical-honesty), re-runs the headline number to reproduce it, BLOCKS on fatal, writes an audit log to `_DataMetricPulls/pacing_backtest/audits/`. In the /pre-commit chain when backtest files change. It returns a verdict, it does NOT certify a strategy works.

**Periodic deep sweeps (NOT per-PR — invoke on demand):**
- `@qa-code-quality` — orphan code, duplicates, hotfix layering, bloat, bad abstractions. Run weekly or before major refactors.
- `@qa-architecture-quality` — module boundaries, abstraction leaks, dependency direction, convention compliance vs CLAUDE.md. Run monthly or before adding a new module.

**On-demand utilities:**
- `@api-integrator` — adding new Polymarket or data source endpoints
- `@doc-updater` — after any feature merge or at end of session
- `@module-scaffolder` — creating new trading modules

**External non-AI tooling**:
- **SonarCloud** runs on every PR via GitHub Action. Catches cyclomatic complexity, real bugs, dead code, security smells. Free (public repo). Findings show up as PR comments — review them alongside the agent reports.

## Available Commands
- `/pre-commit` — chain QA + strategy + risk + verify before commit
- `/check-status` — project status overview
- `/post-session` — end-of-session doc updates

## Available Skills
- `polymarket-api` — auto-loads API rules when touching CLOB/Gamma/xTracker code
- `betting-strategy` — auto-loads when touching sizing, Kelly, risk, ensemble logic

## Conventions
- Feature branches for strategy changes; /feature-dev for 3+ file changes
- Test with docker-compose before deploy; subagents for research; @qa-code-bug-hunter for code review

## Autonomy
- **Use Claude in Chrome and Claude Preview MCP tools proactively whenever the task is browser-actionable.** This includes Railway deploys, redeploys, dashboard checks, deploy log inspection, and any other web-based action that would otherwise require user clicks. Do not ask the user to "open the dashboard" or "click redeploy" — drive the browser via MCP and report results.
- Only escalate to the user when an action genuinely requires their physical input (e.g. 2FA codes, password entry on a locked-out account, financial confirmation).

## After Every Bug Fix — TWO PLACES (mandatory)
1. **`_ImportantConfigFiles/lessons.md`** — human-readable changelog of what went wrong (full narrative)
2. **`~/.claude/projects/C--Users-darwi-OneDrive-Desktop-Claude-Code-Personal-PolyMarket-Bot/memory/lesson_<slug>.md`** — auto-loaded memory file with the RULE (concise, actionable). Then add a one-line pointer to `memory/MEMORY.md` under the "Hard-won lessons" section.

Why both: lessons.md is the human log (full context, never trimmed). Memory files auto-load into every new session so vAI obeys the rule without being told. If you only write to lessons.md, vAI will repeat the mistake — those files are NOT auto-loaded.

Format for the memory file (frontmatter required):
```
---
name: lesson-<kebab-case-slug>
description: One-line summary of the rule
metadata:
  type: feedback
---
[Rule statement]

**Why:** [Date + what happened + impact]

**How to apply:** [Numbered actions to prevent recurrence]
```

## Daily Backfill Status Check
**On the first user prompt of the day**, query Supabase `backfill_progress` table and report any handle where `is_complete = false`. As of 2026-05-03, Trump (`realDonaldTrump`) is COMPLETE (32,880 posts, walked back to Feb 2022). No action needed unless a new backfill is started or a handle's `is_complete` flips back to false.

## Documentation Rules
- Update FEATURES.md after every feature addition or change
- Update HANDOFF.md at end of major work sessions
- All .md files: 150 lines max
