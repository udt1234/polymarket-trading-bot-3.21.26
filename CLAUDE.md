# PolyMarket Bot

Automated Polymarket trading bot deployed on Railway.

## ⭐ SPIKE TRADING: Bracket Recommendations (parquet-validated 2026-05-06)
**When user asks "which brackets should Spike trade" or any variant, read `_ImportantConfigFiles/SPIKE_BRACKETS.md` FIRST and surface it.** Also remind the user its data window is Sep 2025 to May 2026.

## Tech Stack
- Python, Docker, Railway
- Next.js web dashboard (web/ folder)

## Key Files
- docker-compose.yml, railway.toml
- web/: Next.js dashboard with Recharts
- _ImportantConfigFiles/: detailed architecture, strategy, features, API docs

## Deploy
- Push to Railway via git
- Config in .env (never commit)

## MCP (project-specific)
- polymarket: Custom Polymarket API server

## Credentials
- Master credential store: `~/.credentials/shared.env`
- Vars needed: POLYMARKET_API_KEY, SECRET, PASSPHRASE, PRIVATE_KEY + Supabase keys
- Copy to local `.env`: never commit

## Data Storage
- **ALL backtest data lives under `_DataMetricPulls/canonical/`**: see "Canonical Data Layer" section below
- Source-of-truth raw post parquets: `_DataMetricPulls/{trump,elon}_posts_raw.parquet`
- Raw trade archive: `_DataMetricPulls/canonical/_raw_imports/api_trades_v2/` (one parquet per auction)
- Never commit large data files: add to .gitignore

## Retention + Parquet Archive (2026-05-22)
Supabase live retention windows, the parquet archive path, the cleanup/archive schedulers and `parquet_archive.read_table_range()` are in `_ImportantConfigFiles/DATA_LAYER.md`. Read it before changing retention or reading data older than the live window.

## Canonical Data Layer (2026-05-28): Single Source of Truth for ALL Backtests

**`_DataMetricPulls/canonical/` is the ONLY data source backtests may read from.**
Tables, key columns, the raw trade archive, builder scripts and the QA Sheet are in `_ImportantConfigFiles/DATA_LAYER.md`. Read it before any backtest or builder run.

**Order matters: anything that touches `_raw_imports/` must be followed by `04_build_prices.py`.** `prices` is derived; leaving it stale is what produced the 2026-07 winner-coverage bug.

### Rules for new backtests
1. **Read canonical/ only.** If you need data not in canonical/, add to a builder script, don't write a one-off parquet.
2. **Always use `ts_et` when applying xTracker auction windows** (Friday 12 PM ET → Friday 12 PM ET). Never anchor on UTC hours.
3. **Filter `counts_for_auction = True` on posts** before counting toward an auction.
4. **Filter `confidence in ('high','medium')` on auctions** to skip unresolved/ambiguous.
5. **Treat the underlying `trump_posts_raw.parquet` / `elon_posts_raw.parquet` as inputs, not data.** They feed the canonical builder.
6. **`@backtest-builder` BUILDS it. `@backtest-auditor` AUDITS it. Never hand-write a backtest.** See "Backtest Agents Are The Default" below.
7. **Never substitute a floor for a missing price: EXCLUDE the auction.** If the WINNING bracket has no price row at time T, that auction is inadmissible for any model-vs-market comparison. Defaulting it to `1e-6`/epsilon/uniform fabricates the market's log loss and inverts the result. Run `15_verify_winner_coverage.py` before quoting any model-vs-market number, and report admissible n separately from full n.

## Backtest Agents Are The Default (Non-Negotiable)
- **`@backtest-builder` is the ONLY way a backtest gets written.** Any request meaning "backtest / simulate / what if / test this strategy / find patterns in the history / measure this model" routes to the builder FIRST. Claude does not hand-write the script.
- **`@backtest-auditor` is the ONLY way a backtest result gets trusted.** Every builder output goes to the auditor before a number is quoted, a model is locked, or a param is changed. No exceptions, including negative results.
- **Applies to forecast-accuracy and calibration studies too**, not just P&L. The auditor scope-gates the diagnostic case (`.claude/agents/backtest-auditor.md` line 13).
- **Name the agent out loud, every time.** Say "invoking @backtest-builder to build X" and "invoking @backtest-auditor to audit X", and attribute every reported number to the agent that produced it. The user must never have to guess who wrote the code behind a number.
- **Only exception:** a one-line throwaway probe (row count, date range, column check) may run inline. The moment it fits a model, splits train/test, or produces a number the user might act on, it goes to the builder.
- Claude's role is scoping the question, pre-registering the rule list and held-out span, relaying the verdict, and recommending the next move.

## Non-Negotiable Rules
- **ALWAYS limit orders**: NEVER market orders. Every order specifies a `price`.
- NEVER hardcode API keys: use env vars only
- NEVER place real orders without PAPER_MODE=false + ENV=production guard
- NEVER modify position limits without updating STRATEGY.md + risk-rules.md
- ALWAYS use exponential backoff on WebSocket reconnection
- ALWAYS run all 15 risk checks before order placement
- Prefer deleting code over adding it

## Module Architecture Rules (Non-Negotiable)
**Goal: editing one module never breaks another. New modules drop in cleanly.**

Read `_ImportantConfigFiles/MODULE_ARCHITECTURE.md` before creating, moving or refactoring any module. Its "Quick Rules" section holds the 8 rules: module folder layout, no cross-module imports, shared code in `api/modules/shared/`, no hardcoded module names in engine/router code, per-module settings and health, `@module-scaffolder` for new modules, and test scope on refactors.

## Available Agents

**Per-PR (runs in /pre-commit chain):**
- `@qa-code-bug-hunter`: bugs, edge cases, security, performance, trading-specific risks. After implementation, before PR.
- `@strategy-reviewer`: before committing signal/pacing/projection changes
- `@risk-auditor`: before going live, audit all money-touching code
- `@verify-bot`: end-to-end paper trading verification (NOT a backtester)
- `@backtest-builder`: **writes Polymarket-native backtests that pass the auditor BY CONSTRUCTION** (canonical data, noon-ET window, event-driven, real-L2 maker fills, taker-fee truth, THE WALL, imports `locked_pace`, emits RUN_META). The auditor's twin: builder proposes, auditor disposes. Hands off to `@backtest-auditor` for the verdict; never certifies its own result. Use for any "backtest this / simulate / what if".
- `@backtest-auditor`: **catches WRONG backtests before you trust the number.** Invoke after writing/changing any backtest, before quoting a P&L/ROI/win-rate, or before locking a model/param. 4 adversarial passes (A data-integrity / B metric-validity / C instruction-compliance / D statistical-honesty), re-runs the headline number to reproduce it, BLOCKS on fatal, writes an audit log to `_DataMetricPulls/pacing_backtest/audits/`. In the /pre-commit chain when backtest files change. It returns a verdict, it does NOT certify a strategy works.

**Periodic deep sweeps (NOT per-PR: invoke on demand):**
- `@qa-code-quality`: orphan code, duplicates, hotfix layering, bloat, bad abstractions. Run weekly or before major refactors.
- `@qa-architecture-quality`: module boundaries, abstraction leaks, dependency direction, convention compliance vs CLAUDE.md. Run monthly or before adding a new module.

**On-demand utilities:**
- `@api-integrator`: adding new Polymarket or data source endpoints
- `@doc-updater`: after any feature merge or at end of session
- `@module-scaffolder`: creating new trading modules

**External non-AI tooling**:
- **SonarCloud** runs on every PR via GitHub Action. Catches cyclomatic complexity, real bugs, dead code, security smells. Free (public repo). Findings show up as PR comments: review them alongside the agent reports.

## Available Commands
- `/pre-commit`: chain QA + strategy + risk + verify before commit
- `/check-status`: project status overview
- `/post-session`: end-of-session doc updates

## Available Skills
- `polymarket-api`: auto-loads API rules when touching CLOB/Gamma/xTracker code
- `betting-strategy`: auto-loads when touching sizing, Kelly, risk, ensemble logic

## Conventions
- Feature branches for strategy changes; /feature-dev for 3+ file changes
- Test with docker-compose before deploy; subagents for research; @qa-code-bug-hunter for code review

## Autonomy
- **Use Claude in Chrome and Claude Preview MCP tools proactively whenever the task is browser-actionable.** This includes Railway deploys, redeploys, dashboard checks, deploy log inspection, and any other web-based action that would otherwise require user clicks. Do not ask the user to "open the dashboard" or "click redeploy": drive the browser via MCP and report results.
- Only escalate to the user when an action genuinely requires their physical input (e.g. 2FA codes, password entry on a locked-out account, financial confirmation).

## After Every Bug Fix: TWO PLACES (mandatory)
1. **`_ImportantConfigFiles/lessons.md`**: human-readable changelog of what went wrong (full narrative)
2. **`~/.claude/projects/C--Users-darwi-OneDrive-Desktop-Claude-Code-Personal-PolyMarket-Bot/memory/lesson_<slug>.md`**: auto-loaded memory file with the RULE (concise, actionable). Then add a one-line pointer to `memory/MEMORY.md` under the "Hard-won lessons" section.

Why both: lessons.md is the human log (full context, never trimmed). Memory files auto-load into every new session so vAI obeys the rule without being told. If you only write to lessons.md, vAI will repeat the mistake: those files are NOT auto-loaded.

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
