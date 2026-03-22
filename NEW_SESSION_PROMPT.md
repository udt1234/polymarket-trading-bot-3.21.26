# Polymarket Bot — New Session Prompt

Copy everything below this line and paste it as your first message in a new Claude Code session opened from the `PolyMarket` folder (`C:\Users\darwi\OneDrive\Desktop\Claude Code\PolyMarket`).

---

# Context: Polymarket Trading Bot — Major Redesign

## What Exists Today

I have an existing Polymarket trading bot in this folder. Here's what's already built:

### Current Architecture
```
PolyMarket/
├── bot/                          # Trading bot (Phase 1 complete)
│   ├── main.py                   # Entry point (python main.py --paper)
│   ├── config.py                 # Global settings, credentials
│   ├── core/                     # Engine, risk manager, executor, order/position managers
│   ├── strategies/               # Auto-discovered strategy plugins
│   │   └── nyc_temperature/      # NYC temp strategy (stub with test signals)
│   ├── backtesting/              # Backtest engine
│   ├── dashboard/                # Basic FastAPI dashboard at localhost:8080
│   ├── bot.db                    # Bot's SQLite DB (orders, positions, trades, signals)
│   └── HANDOFF.md                # Detailed session notes
├── polymarket.db                 # 200MB+ data DB (80K+ snapshots, settlements, weather)
├── nightly_sync.py               # Automated data pipeline (Windows Task Scheduler)
├── export_to_sqlite.py           # Google Sheets → SQLite export
├── Code.js / ControlPanel.html   # Apps Script collector (Google Sheets)
├── mcp-polymarket/               # MCP server for Polymarket (server.py)
├── UnifiedDashboard/             # Older dashboard attempt with Apps Script
├── _InstructionalFiles/          # Documentation (trading_bot.md, deployment_playbook.md, etc.)
├── data-tools/                   # Data utilities
├── docs/                         # Additional docs
├── PROJECT_STATUS.md             # Current state as of Feb 26
├── WHATS_BEEN_BUILT.md           # Plain-English overview
└── .mcp.json                     # MCP config (Google Sheets)
```

### What Works
- Bot engine with scheduler (runs every 5 min in paper mode)
- Strategy auto-discovery (drop a package in strategies/, engine finds it)
- Risk manager: Kelly criterion (0.25x fractional), edge threshold, spread limit, settlement decay, correlation limits, drawdown check
- Paper executor (simulated fills)
- Order state machine (CREATED → PENDING_NEW → LIVE → FILLED/CANCELLED)
- Position tracking with P&L
- Signal logging (approved + rejected, with risk reasoning)
- Backtesting against historical data
- SQLite data pipeline: Google Sheets → polymarket.db (80K+ rows, nightly automated sync)
- NYC Temperature strategy stub (generates test signals)
- Basic FastAPI dashboard at localhost:8080
- GitHub repo: https://github.com/udt1234/polymarket-trading-bot

### 6-Phase Plan (from IMPLEMENTATION_PLAN.md)
- Phase 1: Foundation — Core Engine + Paper Trading ✅ DONE
- Phase 2: NYC Temperature Strategy (Real ML) — NOT STARTED
- Phase 3: Dashboard — BASIC VERSION EXISTS
- Phase 4: Real-Time Data (WebSocket) — NOT STARTED
- Phase 5: Live Execution — NOT STARTED
- Phase 6: Additional Strategies — NOT STARTED

## What I Want to Build (Redesign)

I want to evolve this into a **full-featured Polymarket trading platform** with these pillars:

### 1. Global Settings Panel
- Load/configure statistical tests (Bayesian, Kelly Criterion, Monte Carlo, Brier Score, Walk-Forward Validation)
- Tests should be pluggable via the web UI (JSON config + Python module, no coding to add new ones)
- Global risk settings: bankroll, max portfolio/single-market/correlated exposure, daily/weekly loss limits, max drawdown threshold, min edge threshold, slippage tolerance, gas budget, paper trading toggle, auto-cancel on disconnect
- Notification channels (Discord/Telegram/email)

### 2. Analytics Dashboard
- Pull from all active modules/auctions
- Core metrics: Total P&L, ROI, win rate (7d/30d/all), Sharpe ratio, Sortino ratio, max drawdown, Calmar ratio, profit factor, Brier score, average edge captured
- Views: Portfolio overview, module drill-down, strategy comparison, risk dashboard, trade log, calibration chart
- Operational metrics: open positions, fill rate, API latency, gas costs

### 3. Modular Auction System
- Each market (NY Temperature, Trump Truth Social, etc.) is a module
- Per-module settings: market IDs, active strategy, strategy overrides, budget allocation, position limits, data sources, resolution date, liquidity requirements, A/B test config, backtest results, alert rules, auto-pause rules
- A/B test strategies within modules (split budget across variants, track independent P&L)
- Add new modules through the UI without coding

### 4. Additional Components (from research)
- **Risk Manager (pre-trade gate)** — every order passes through 15+ checks before execution
- **Resolution Monitor** — track UMA oracle proposals, disputes, auto-unwind
- **Liquidity Analyzer** — order book depth, slippage estimation
- **Correlation Engine** — map relationships between positions, prevent over-concentration
- **Event/News Feed Integration** — RSS, Twitter/X, news APIs → trigger strategy re-evaluation
- **Wallet & Gas Manager** — USDC balance, gas costs, transaction retries
- **Audit Trail** — immutable decision log (why each trade was placed)
- **Alert System** — price, P&L, resolution, risk limit, system health alerts
- **Calibration Tracker** — predicted probabilities vs actual outcomes over time
- **Logs Tab** — decision log, execution log, system log, risk log (filterable, searchable, real-time streaming, exportable)

### 5. Frontend & Access
- **Next.js + Tailwind + shadcn/ui** for the web dashboard
- **Light mode default**, dark mode toggle available
- **PWA** (Progressive Web App) so I can install it on my iPhone home screen
- Must be accessible from work PC, home PC, and phone
- Deploy to **Railway** ($5-12/mo) for always-on hosting
- **Supabase** for Postgres database + auth
- Tab bar: Overview | Portfolio | Strategy | Trades | Logs | Settings

### 6. Design Reference
- I like the DefibotX/Envato Market style (dark cards, clean metrics, area charts)
- But start in **light mode** with dark mode toggle
- Same card layout: Portfolio Value, Total Profit, Win Rate, Market Condition across top
- Performance chart with time range selector
- AI Insights section at bottom

## What I Need You To Do

1. **Read the existing codebase** — check `_InstructionalFiles/`, `bot/HANDOFF.md`, `PROJECT_STATUS.md`, `WHATS_BEEN_BUILT.md`, `bot/IMPLEMENTATION_PLAN.md` to understand what exists
2. **Create all required .md files** (respecting the 200-line max rule):
   - `CLAUDE.md` — project conventions, architecture, build/run commands
   - `PROJECT.md` — overview, goals, tech stack, status
   - `HANDOFF.md` — current state (update the existing one)
   - `DESIGN.md` — UI/UX decisions, component structure, light/dark mode specs
   - `ARCHITECTURE.md` — system architecture, data flow, deployment
   - `STRATEGY.md` — trading strategies catalog, parameters, when to use each
   - `API.md` — Polymarket API integration notes, endpoints, auth, rate limits
3. **Create a GitHub repo** (or use existing: https://github.com/udt1234/polymarket-trading-bot)
4. **Scaffold the new project structure** — integrate with existing bot code, add Next.js frontend, restructure for the modular auction system
5. **Update .mcp.json** — the current one has Google Sheets config, which we keep. Add any additional MCP servers needed for this project.
6. **Move credentials to .env** — there's a `polymarket_credentials.json` and `google_sheets_service_account_credentials.json` (in UnifiedDashboard/) that should be env vars, not JSON files on disk

## Folder Cleanup Note
- The `TruthSocial` folder at `Desktop/Claude Code/TruthSocial` has a `.env` with Google Sheets service account credentials already converted to env vars, plus a `.gitignore`. Copy those into this project and I'll delete the TruthSocial folder.
- `UnifiedDashboard/google_sheets_service_account_credentials.json` — delete after moving to .env
- `UnifiedDashboard/polymarket_credentials.json` — delete after moving to .env
- Root `polymarket_credentials.json` — delete after moving to .env

## Key Constraints
- All .md files: 200 lines max, split into numbered parts if needed
- No over-engineering — build what's needed, not what's hypothetical
- Use existing bot code as foundation — don't rewrite what works
- Python backend (FastAPI), Next.js frontend, Supabase (Postgres + auth)
- Deploy to Railway for always-on access from any device
- PWA for iOS access without native app
