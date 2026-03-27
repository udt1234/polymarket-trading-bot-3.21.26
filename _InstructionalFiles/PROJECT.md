# PolyMarket Bot — Project Overview

## Goal
Evolve existing Polymarket paper trading bot into a full-featured trading platform accessible from any device (work PC, home PC, iPhone via PWA).

## Status: Phase 2 — Platform Redesign
| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Core Engine + Paper Trading | DONE |
| 2 | Platform Redesign (this repo) | IN PROGRESS |
| 3 | NYC Temperature ML Strategy | NOT STARTED |
| 4 | Real-Time WebSocket Feeds | NOT STARTED |
| 5 | Live Execution | NOT STARTED |
| 6 | Additional Strategies | NOT STARTED |

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Trading Engine | Python 3.11+, FastAPI, APScheduler |
| Frontend | Next.js 14+, TypeScript, Tailwind, shadcn/ui |
| Database | Supabase (Postgres + Auth + RLS) |
| Hosting | Railway |
| Mobile | PWA (next-pwa) |
| Market API | Polymarket CLOB via py-clob-client |
| Data Pipeline | SQLite (local) → Supabase (prod) |

## Platform Pillars

### 1. Global Settings Panel
- Pluggable statistical tests (Bayesian, Kelly, Monte Carlo, Brier, Walk-Forward)
- Risk settings: bankroll, exposure limits, loss limits, drawdown threshold
- Notification channels (Discord/Telegram/email)

### 2. Analytics Dashboard
- P&L, ROI, win rate, Sharpe, Sortino, max drawdown, Calmar, profit factor
- Portfolio overview, module drill-down, strategy comparison, trade log
- Operational: fill rate, API latency, gas costs

### 3. Modular Auction System
- Each market = a module (NYC Temp, Trump Truth Social, etc.)
- Per-module: strategy, budget, position limits, data sources, A/B testing
- Add new modules through UI without coding

### 4. Supporting Components
- Risk Manager (15+ pre-trade checks)
- Resolution Monitor (UMA oracle tracking)
- Liquidity Analyzer (order book depth, slippage)
- Correlation Engine (position relationships)
- Audit Trail (immutable decision log)
- Alert System (price, P&L, risk, health)

## Dependencies
- Polymarket CLOB API + Gamma API (market data)
- Supabase project (Postgres + Auth)
- Railway account (deployment)
- Google Sheets service account (legacy data pipeline)

## GitHub
- Repo: https://github.com/udt1234/polymarket-trading-bot
- Branch strategy: `main` (stable), `dev` (active work), feature branches

## Key Decisions
- Keep existing Python bot as-is — wrap with new API layer
- SQLite stays for local dev, Supabase Postgres for prod
- Light mode default, dark mode toggle
- PWA over native app for iPhone access
