# PolyMarket Bot — Architecture

## System Overview
```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Next.js PWA   │────▶│   FastAPI (API)   │────▶│  Supabase   │
│   (web/)        │◀────│   (api/)          │◀────│  (Postgres) │
│   Port 3000     │     │   Port 8000       │     │             │
└─────────────────┘     └──────┬───────────┘     └─────────────┘
                               │
                        ┌──────▼───────────┐
                        │  Trading Engine   │
                        │  (bot/)           │
                        │  - Scheduler      │
                        │  - Risk Manager   │
                        │  - Executor       │
                        │  - Strategies     │
                        └──────┬───────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Polymarket CLOB    │
                    │  (py-clob-client)   │
                    └─────────────────────┘
```

## Data Flow

### Signal → Trade Pipeline
1. **Scheduler** fires strategy evaluation (every N seconds)
2. **Strategy** analyzes market data → produces `Signal` (market, side, confidence)
3. **Risk Manager** gates signal through 15+ checks (Kelly sizing, exposure, drawdown)
4. **Executor** places order (paper: simulate, live: py-clob-client → CLOB)
5. **Order Manager** tracks state machine (CREATED → LIVE → FILLED)
6. **Position Manager** updates P&L, exposure

### Data Pipeline
```
Polymarket Gamma API → nightly_sync.py → SQLite (local)
                                            ↓
                                      Supabase (prod)
```
- 80K+ market snapshots in `polymarket.db`
- Nightly sync via Windows Task Scheduler
- Future: WebSocket feeds for real-time data

## API Layer (api/)
The API wraps the bot engine for the frontend:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/portfolio` | GET | Current positions, P&L |
| `/api/trades` | GET | Trade history (paginated) |
| `/api/signals` | GET | Signal log (approved + rejected) |
| `/api/modules` | GET/POST | List/create auction modules |
| `/api/modules/{id}` | PUT/DELETE | Update/remove module |
| `/api/settings` | GET/PUT | Global risk + test config |
| `/api/metrics` | GET | Dashboard metrics (Sharpe, etc.) |
| `/ws/feeds` | WS | Real-time price + trade updates |

## Database Schema (Supabase)

### Core Tables (migrated from SQLite)
- `orders` — order state, market, side, size, price, timestamps
- `positions` — market, side, size, avg_price, unrealized_pnl
- `trades` — filled orders with execution details
- `signals` — strategy outputs (approved/rejected + reasoning)
- `daily_pnl` — daily portfolio snapshots

### New Tables
- `modules` — auction module config (market_id, strategy, budget, limits)
- `module_ab_tests` — A/B test variants per module
- `statistical_tests` — pluggable test configs (JSON)
- `alerts` — alert rules + history
- `audit_log` — immutable decision trail

### Auth
- Supabase Auth (email/password) — single user for now
- RLS policies: all data scoped to authenticated user

## Deployment (Railway)

### Services
1. **api** — FastAPI + bot engine (Python)
2. **web** — Next.js frontend (Node.js)
3. **worker** — Scheduler/strategy runner (Python, optional separate service)

### Environment Variables
All secrets via Railway env vars — mirrors `.env`:
```
POLYMARKET_PRIVATE_KEY, POLYMARKET_API_KEY, POLYMARKET_SECRET
SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY
GOOGLE_SA_* (service account vars for Sheets pipeline)
PAPER_MODE, DEFAULT_INTERVAL
```

## Local Development
```bash
docker-compose up  # Starts API (8000) + Web (3000) + local Supabase
```
Or run individually — see CLAUDE.md for commands.
