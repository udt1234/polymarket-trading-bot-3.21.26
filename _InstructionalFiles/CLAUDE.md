# PolyMarket Bot — Project Conventions

## Purpose
Polymarket prediction market trading platform. Python FastAPI backend + Next.js frontend + Supabase + Railway.

## Architecture
```
PolyMarket_Bot/
├── api/                    # Python FastAPI backend
│   ├── main.py             # Uvicorn entry, CORS, lifespan
│   ├── config.py           # Pydantic settings from .env
│   ├── dependencies.py     # Supabase client singleton
│   ├── routers/            # REST endpoints (8 routers)
│   ├── services/           # Engine, risk, executor, orders, positions, market data
│   ├── modules/            # Auto-discovered auction modules
│   │   ├── base.py         # BaseModule interface
│   │   └── truth_social/   # First module (pacing, projection, regime, signals)
│   └── ws/                 # WebSocket feeds
├── web/                    # Next.js 14 frontend
│   ├── app/                # App Router (7 pages + login)
│   ├── components/         # layout, dashboard, modules, shared
│   ├── lib/                # api.ts, supabase.ts, utils.ts
│   └── public/             # PWA manifest, icons
├── supabase/
│   └── migrations/         # 001_initial.sql (13 tables + RLS + seeds)
├── _InstructionalFiles/    # Spec docs
├── .env.example            # All env var templates
├── docker-compose.yml      # Local dev (placeholder)
└── railway.toml            # Deploy config (placeholder)
```

## Tech Stack
- **Backend**: Python 3.11+, FastAPI, APScheduler, py-clob-client, httpx
- **Frontend**: Next.js 14, Tailwind CSS, shadcn/ui patterns, Recharts, Lucide icons
- **Database**: Supabase (Postgres) with RLS
- **Auth**: Supabase Auth (email/password)
- **Deploy**: Railway (local dev first)
- **PWA**: manifest.json for iOS home screen install

## Build & Run
```bash
# API server
cd api && pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000

# Frontend
cd web && npm install && npm run dev  # localhost:3000
```

## Key Features
- **Module auto-discovery**: Drop a package in `api/modules/`, engine finds it
- **Risk manager**: 11 checks (Kelly, drawdown, exposure, settlement decay, etc.)
- **Circuit breaker**: Auto-halt after N consecutive losses, cooldown period
- **Shadow mode**: Paper + live side-by-side comparison
- **Order state machine**: CREATED → SUBMITTED → LIVE → FILLED → SETTLED
- **Paper/Live executor swap**: Toggle without changing strategy code

## Documentation Rules
- **Update FEATURES.md** after every feature addition or change
- **Update HANDOFF.md** at end of major work sessions

## Conventions
- 200-line max on all .md files
- Secrets in `.env`, never hardcode
- Conventional commits (feat:, fix:, refactor:, docs:, chore:)
- No over-engineering — build what's needed now
- DefibotX = visual inspiration only (layout/cards/charts), not content

## Nav Structure
Dashboard | Modules | Portfolio | Trades | Analytics | Logs | Settings
