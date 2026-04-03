# DEPRECATED — Do Not Use

This file is obsolete. Claude Code now auto-loads context from:
- `CLAUDE.md` (project root) — conventions, agents, rules
- `_InstructionalFiles/` — architecture, strategy, features, API, design, handoff
- `.claude/` — agents, skills, commands, settings

No manual prompt pasting needed. Just open Claude Code in the project directory.

---

# (Original content below for reference only)

---

# Polymarket Trading Bot — Major Redesign

## What Already Exists in This Folder

This project has a working Phase 1 trading bot. Read these files to get full context:
- `bot/HANDOFF.md` — detailed build log, file list, test results, architecture decisions
- `PROJECT_STATUS.md` — data state, component status, pipeline details
- `WHATS_BEEN_BUILT.md` — plain-English overview of the whole system
- `bot/IMPLEMENTATION_PLAN.md` — 6-phase roadmap
- `_InstructionalFiles/` — trading_bot.md, deployment_playbook.md, sqlite_schema.md, etc.

### Quick Summary of What Works
- Bot engine with 5-min scheduler, paper trading mode (`python bot/main.py --paper`)
- Strategy auto-discovery (drop a package in `bot/strategies/`, engine finds it)
- Risk manager: Kelly criterion (0.25x), edge threshold, spread limit, settlement decay, correlation limits, drawdown check
- Paper executor with simulated fills, order state machine, position tracking with P&L
- Backtesting engine against historical data
- SQLite data pipeline: Google Sheets → polymarket.db (80K+ rows, nightly automated sync via Windows Task Scheduler)
- NYC Temperature strategy stub (test signals only — real ML is Phase 2)
- Basic FastAPI dashboard at localhost:8080
- MCP server for Polymarket in `mcp-polymarket/`
- GitHub repo: https://github.com/udt1234/polymarket-trading-bot

### Phase Status
- Phase 1: Foundation + Paper Trading — DONE
- Phase 2: NYC Temperature ML Strategy — NOT STARTED
- Phase 3: Dashboard — BASIC VERSION EXISTS
- Phase 4: Real-Time WebSocket Data — NOT STARTED
- Phase 5: Live Execution — NOT STARTED
- Phase 6: Additional Strategies — NOT STARTED

## What I Want to Build (Redesign)

### 1. Global Settings Panel
- Pluggable statistical tests (Bayesian, Kelly Criterion, Monte Carlo, Brier Score, Walk-Forward Validation)
- Add new tests via web UI (JSON config + Python module) — no coding required
- Global risk settings: bankroll, max portfolio/single-market/correlated exposure, daily/weekly loss limits, max drawdown, min edge threshold, slippage tolerance, gas budget, paper trading toggle, auto-cancel on disconnect
- Notification channels (Discord/Telegram/email)

### 2. Analytics Dashboard
- Pulls from all active modules/auctions
- Metrics: Total P&L, ROI, win rate (7d/30d/all), Sharpe ratio, Sortino ratio, max drawdown, Calmar ratio, profit factor, Brier score, average edge captured
- Views: Portfolio overview, module drill-down, strategy comparison, risk dashboard, trade log, calibration chart
- Operational: open positions, fill rate, API latency, gas costs

### 3. Modular Auction System
- Each market (NY Temperature, Trump Truth Social, etc.) is a module
- Per-module: market IDs, active strategy, strategy overrides, budget allocation, position limits, data sources, resolution date, liquidity requirements, A/B test config, backtest results, alert rules, auto-pause
- A/B test strategies within modules (split budget, track independent P&L)
- Add new modules through the UI — no coding

### 4. Additional Components
- Resolution Monitor — track UMA oracle proposals, disputes, auto-unwind
- Liquidity Analyzer — order book depth, slippage estimation
- Correlation Engine — map position relationships, prevent over-concentration
- Event/News Feed Integration — RSS, Twitter/X, news APIs → trigger strategy re-evaluation
- Wallet & Gas Manager — USDC balance, gas costs, transaction retries
- Audit Trail — immutable decision log (why each trade was placed)
- Alert System — price, P&L, resolution, risk limit, system health
- Calibration Tracker — predicted probabilities vs actual outcomes over time

### 5. Frontend & Access
- **Next.js + Tailwind + shadcn/ui** for the web dashboard
- **Light mode default**, dark mode toggle
- **PWA** (Progressive Web App) — installable on iPhone home screen, no native app needed
- Accessible from work PC, home PC, and phone (all via browser/PWA)
- Deploy to **Railway** ($5-12/mo) for always-on hosting
- **Supabase** for Postgres database + auth
- Tab bar: **Overview | Portfolio | Strategy | Trades | Logs | Settings**

### 6. Logs Tab
- Decision log — every trade decision with reasoning
- Execution log — orders submitted, filled, cancelled, rejected
- System log — WebSocket connects/disconnects, API errors, rate limits
- Risk log — when limits are hit
- Filterable by severity, module, strategy, date range
- Searchable with real-time streaming, exportable to CSV/JSON

### 7. Design
- DefibotX/Envato Market style: clean cards, area charts, metric tiles
- Light mode default with dark mode toggle
- Top cards: Portfolio Value, Total Profit, Win Rate, Market Condition
- Performance chart with time range selector
- AI Insights section at bottom

## Tasks for This Session

1. **Read the existing codebase** — check all files listed in "What Already Exists" above
2. **Create project .md files** (200-line max per file, split if needed):
   - `CLAUDE.md` — project conventions, architecture, build/run commands
   - `PROJECT.md` — overview, goals, tech stack, status
   - `HANDOFF.md` — update the existing root-level one
   - `DESIGN.md` — UI/UX decisions, component structure, light/dark mode
   - `ARCHITECTURE.md` — system architecture, data flow, deployment
   - `STRATEGY.md` — trading strategies catalog, parameters, when to use
   - `API.md` — Polymarket API integration notes, endpoints, auth, rate limits
3. **Create GitHub repo** (or use existing: https://github.com/udt1234/polymarket-trading-bot)
4. **Scaffold the new project structure** — integrate existing bot code, add Next.js frontend, restructure for modular auction system
5. **Update .mcp.json** — keep Google Sheets config, add anything else needed
6. **Credential cleanup**:
   - `polymarket_credentials.json` (project root) → move to `.env`, delete JSON
   - `UnifiedDashboard/google_sheets_service_account_credentials.json` → move to `.env`, delete JSON
   - `UnifiedDashboard/polymarket_credentials.json` → move to `.env`, delete JSON
   - NOTE: The Google SA private key was accidentally exposed in a prior session. **Rotate the key in Google Cloud Console** before going live.

## Constraints
- All .md files: 200 lines max, split into numbered parts if needed
- Don't over-engineer — build what's needed now
- Use existing bot code as foundation — don't rewrite what works
- Python backend (FastAPI), Next.js frontend, Supabase (Postgres + auth)
- Deploy to Railway for always-on access
- PWA for iOS — no native app
