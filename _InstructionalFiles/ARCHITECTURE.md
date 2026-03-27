# PolyMarket Bot — Architecture

## System Overview
```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Next.js PWA   │────▶│   FastAPI (API)   │────▶│  Supabase   │
│   (web/)        │◀────│   (api/)          │◀────│  (Postgres) │
│   Port 3000     │     │   Port 8000       │     │  + Auth     │
└─────────────────┘     └──────┬───────────┘     └─────────────┘
                               │
                        ┌──────▼───────────┐
                        │  Trading Engine   │
                        │  - Scheduler      │
                        │  - Risk Manager   │
                        │  - Circuit Breaker│
                        │  - Executor (P/L) │
                        │  - Shadow Mode    │
                        │  - Module Registry│
                        └──────┬───────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Polymarket APIs    │
                    │  - CLOB (orders)    │
                    │  - Gamma (markets)  │
                    │  - xTracker (data)  │
                    └─────────────────────┘
```

## Data Flow: Signal → Trade
1. **Scheduler** fires every N seconds (APScheduler)
2. **Module** evaluates its market → produces `Signal`
3. **Risk Manager** runs 11 checks (edge, Kelly, exposure, drawdown, circuit breaker, etc.)
4. **Executor** places order (Paper: simulate fill, Live: py-clob-client)
5. **Shadow Executor** (optional): parallel paper execution for comparison
6. **Order Manager** tracks state: CREATED → SUBMITTED → LIVE → FILLED → SETTLED
7. **Position Manager** updates P&L, exposure

## Module Auto-Discovery
```python
# Drop a package in api/modules/ with a Module class
api/modules/
├── base.py              # BaseModule(ABC) — evaluate() + get_status()
└── truth_social/
    ├── __init__.py       # Module = TruthSocialModule
    ├── module.py         # evaluate() → Signal[]
    ├── pacing.py         # 3 pacing models
    ├── projection.py     # 4-model ensemble → bracket probabilities
    ├── regime.py         # Z-score regime detection
    ├── signals.py        # News modifiers + Kelly sizing
    └── data.py           # xTracker + Google News fetchers
```

## API Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/login` | POST | Supabase auth login |
| `/api/dashboard/metrics` | GET | Overview metrics |
| `/api/dashboard/performance` | GET | P&L time series |
| `/api/modules/` | GET/POST | List/create modules |
| `/api/modules/{id}` | GET/PUT/DELETE | Module CRUD |
| `/api/portfolio/positions` | GET | Open/closed positions |
| `/api/portfolio/exposure` | GET | Exposure breakdown |
| `/api/trades/` | GET | Trade history (paginated) |
| `/api/analytics/summary` | GET | Sharpe, Sortino, etc. |
| `/api/logs/` | GET | Filterable log stream |
| `/api/settings/risk` | GET/PUT | Risk parameters |
| `/ws/feeds` | WS | Real-time updates |

## Database (Supabase)
13 tables: modules, orders, trades, positions, daily_pnl, signals, logs, settings, statistical_tests, module_ab_tests, calibration_log, alerts, audit_log

RLS enabled on all tables. Single-user auth policy.

## Risk Manager Checks
1. Circuit breaker (consecutive losses → cooldown)
2. Edge threshold (min edge to trade)
3. Kelly validation (positive Kelly only)
4. Position size cap (15% max per market)
5. Daily loss limit
6. Weekly loss limit
7. Max drawdown
8. Portfolio exposure limit
9. Single market exposure limit
10. Correlated exposure limit
11. Settlement decay (reduce near resolution)

## Deploy
- **Local first**: `uvicorn` + `npm run dev`
- **Railway**: Single-service deploy via `railway.toml`
- **Docker**: `docker-compose.yml` placeholder for future
