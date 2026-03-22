# PolyMarket Bot — Project Conventions

## Purpose
Full-featured Polymarket trading platform: Python backend (existing bot) + Next.js frontend + Supabase + Railway deployment.

## Architecture
```
PolyMarket_Bot/
├── bot/                    # Python trading engine (migrated from PolyMarket/)
│   ├── main.py             # Entry: python main.py --paper
│   ├── config.py           # Settings, loads .env
│   ├── core/               # Engine, risk, executor, orders, positions
│   ├── strategies/         # Auto-discovered strategy plugins
│   ├── backtesting/        # Backtest engine
│   └── dashboard/          # Legacy FastAPI dashboard
├── api/                    # FastAPI backend (new — serves frontend)
│   ├── main.py             # Uvicorn entry
│   ├── routers/            # REST endpoints
│   └── ws/                 # WebSocket feeds
├── web/                    # Next.js frontend
│   ├── app/                # App Router pages
│   ├── components/         # shadcn/ui + custom
│   └── public/             # PWA manifest, icons
├── supabase/               # Migrations, seed, RLS policies
├── shared/                 # Shared types/constants
├── .env                    # All secrets (never commit)
├── .env.example            # Template with var names
├── docker-compose.yml      # Local dev (API + web + Supabase)
└── railway.toml            # Deploy config
```

## Tech Stack
- **Backend**: Python 3.11+, FastAPI, APScheduler, py-clob-client
- **Frontend**: Next.js 14+, Tailwind CSS, shadcn/ui, TypeScript
- **Database**: Supabase (Postgres) — replaces SQLite for prod
- **Auth**: Supabase Auth (email/password)
- **Deploy**: Railway ($5-12/mo)
- **PWA**: next-pwa for iOS home screen install

## Build & Run
```bash
# Backend
cd bot && pip install -r requirements.txt
python main.py --paper              # Paper trading mode
python main.py --paper --interval 10  # Custom interval (seconds)

# API server
cd api && uvicorn main:app --reload --port 8000

# Frontend
cd web && npm install && npm run dev  # localhost:3000

# Full stack (local)
docker-compose up
```

## Key Commands
```bash
# Data sync (runs nightly via Task Scheduler)
python nightly_sync.py

# Run tests
cd bot && python -m pytest tests/
cd web && npm test
```

## Conventions
- **Strategies**: Drop a package in `bot/strategies/`, engine auto-discovers it
- **200-line max** on all .md files — split into numbered parts if needed
- **Secrets**: All in `.env`, never hardcode or commit
- **Commits**: Conventional commits (feat:, fix:, refactor:, docs:, chore:)
- **No over-engineering**: Build what's needed, not hypothetical features

## Related Docs
- [PROJECT.md](PROJECT.md) — Goals, status, dependencies
- [ARCHITECTURE.md](ARCHITECTURE.md) — System design, data flow
- [DESIGN.md](DESIGN.md) — UI/UX specs
- [STRATEGY.md](STRATEGY.md) — Trading strategies catalog
- [API.md](API.md) — Polymarket API integration
- [HANDOFF.md](HANDOFF.md) — Current state for session continuity

## Original Codebase
Migrated from `Desktop/Claude Code/PolyMarket/` — Phase 1 bot engine is complete and working.
