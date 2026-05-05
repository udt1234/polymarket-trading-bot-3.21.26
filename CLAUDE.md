# PolyMarket Bot

Automated Polymarket trading bot deployed on Railway.

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
- `@qa-reviewer` — after implementation, before PR
- `@verify-bot` — end-to-end paper trading verification (NOT a backtester)
- `@strategy-reviewer` — before committing signal/pacing/projection changes
- `@api-integrator` — adding new Polymarket or data source endpoints
- `@doc-updater` — after any feature merge or at end of session
- `@module-scaffolder` — creating new trading modules
- `@risk-auditor` — before going live, audit all money-touching code

## Available Commands
- `/pre-commit` — chain QA + strategy + risk + verify before commit
- `/check-status` — project status overview
- `/post-session` — end-of-session doc updates

## Available Skills
- `polymarket-api` — auto-loads API rules when touching CLOB/Gamma/xTracker code
- `betting-strategy` — auto-loads when touching sizing, Kelly, risk, ensemble logic

## Conventions
- Use feature branches for strategy changes
- Use /feature-dev for multi-file changes (3+ files)
- Test locally with docker-compose before deploy
- For big coding tasks: use /feature-dev
- For research: use subagents
- For code review: use @qa-reviewer or /feature-dev:code-reviewer

## Autonomy
- **Use Claude in Chrome and Claude Preview MCP tools proactively whenever the task is browser-actionable.** This includes Railway deploys, redeploys, dashboard checks, deploy log inspection, and any other web-based action that would otherwise require user clicks. Do not ask the user to "open the dashboard" or "click redeploy" — drive the browser via MCP and report results.
- Only escalate to the user when an action genuinely requires their physical input (e.g. 2FA codes, password entry on a locked-out account, financial confirmation).

## After Every Bug Fix
Update `_ImportantConfigFiles/lessons.md` with what went wrong and the rule to prevent it.

## Daily Backfill Status Check
**On the first user prompt of the day**, query Supabase `backfill_progress` table and report any handle where `is_complete = false`. As of 2026-05-03, Trump (`realDonaldTrump`) is COMPLETE (32,880 posts, walked back to Feb 2022). No action needed unless a new backfill is started or a handle's `is_complete` flips back to false.

## Documentation Rules
- Update FEATURES.md after every feature addition or change
- Update HANDOFF.md at end of major work sessions
- All .md files: 150 lines max
