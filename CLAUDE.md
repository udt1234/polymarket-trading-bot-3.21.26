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
- Scripts: `scripts/import_cnn_archive.py`, `scripts/fetch_historical_auctions.py`
- Never commit large data files — add to .gitignore

## Non-Negotiable Rules
- **ALWAYS limit orders** — NEVER market orders. Every order specifies a `price`.
- NEVER hardcode API keys — use env vars only
- NEVER place real orders without PAPER_MODE=false + ENV=production guard
- NEVER modify position limits without updating STRATEGY.md + risk-rules.md
- ALWAYS use exponential backoff on WebSocket reconnection
- ALWAYS run all 15 risk checks before order placement
- Prefer deleting code over adding it

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

## After Every Bug Fix
Update `_ImportantConfigFiles/lessons.md` with what went wrong and the rule to prevent it.

## Documentation Rules
- Update FEATURES.md after every feature addition or change
- Update HANDOFF.md at end of major work sessions
- All .md files: 150 lines max
