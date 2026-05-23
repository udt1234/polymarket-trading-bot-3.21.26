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
- Historical data pulls: `_DataMetricPulls/historical/{handle}/`
- Scripts: `scripts/fetch_historical_auctions.py`
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

## Parquet Data Access (Full 3.5-year Polymarket history)
- **Source**: SII-WANGZJ HuggingFace dataset (`SII-WANGZJ/Polymarket_data`) — 1M markets, 766M trade events, Nov 2022 → present
- **Access**: streamed via DuckDB over HTTPS (no local copy required) — see `_DataMetricPulls/duckdb_remote.py`
- **Helper**: `from duckdb_remote import connect; con = connect()` exposes `markets`, `quant`, `trades` views
- **Auth**: free HF token in `~/.credentials/shared.env` as `HF_TOKEN=hf_...` (raises rate limits)
- **Cache**: persistent DuckDB file at `_DataMetricPulls/duckdb_cache/polymarket_remote.duckdb` — materialized tables live here, instant for repeat queries
- **Materialized table**: `per_market_trade_summary` — start/peak/end/low YES price per market (one-time 5-15min remote scan)
- **Analysis script**: `_DataMetricPulls/full_history_analysis.py` — strict-recurring classification + ranking
- **Use this whenever** you need broader historical context than the bot's own `price_snapshots` table (which only goes back ~3 months)
- **Parallel queries OK**: DuckDB inside one process is multi-threaded; multiple Python processes can also query concurrently (bottleneck = bandwidth)

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
