# PolyMarket Bot — Handoff

## Current State (2026-03-21)
- **New repo created**: `PolyMarket_Bot/` — clean start for the platform redesign
- **Original code**: Lives at `Desktop/Claude Code/PolyMarket/` — Phase 1 bot is complete
- **This session**: Set up project scaffolding, MD files, GitHub repo

## What's Done
- [x] `NEW_SESSION_PROMPT.md` — Full redesign spec written
- [x] `CLAUDE.md` — Project conventions, architecture, build/run
- [x] `PROJECT.md` — Overview, goals, tech stack, status
- [x] `HANDOFF.md` — This file
- [x] `DESIGN.md` — UI/UX decisions, component structure
- [x] `ARCHITECTURE.md` — System architecture, data flow, deployment
- [x] `STRATEGY.md` — Trading strategies catalog
- [x] `API.md` — Polymarket API integration notes
- [x] GitHub repo initialized

## What's Next
1. **Migrate bot code** — Copy `bot/` from PolyMarket/ into this repo
2. **Set up .env** — Consolidate credentials from:
   - `PolyMarket/bot/.env` (Polymarket keys)
   - `PolyMarket/polymarket_credentials.json` (API creds)
   - `TruthSocial/.env` (Google Sheets service account)
   - `PolyMarket/UnifiedDashboard/google_sheets_service_account_credentials.json`
3. **Scaffold Next.js frontend** — `npx create-next-app@latest web`
4. **Scaffold FastAPI API layer** — `api/` directory wrapping bot engine
5. **Set up Supabase** — Create project, define schema, enable Auth
6. **Set up Railway** — Connect repo, configure deploy

## Blockers
- None currently

## Open Questions
- Keep `polymarket.db` (203MB) in repo or migrate to Supabase immediately?
- Which notification channel first: Discord or Telegram?
- Railway plan: Starter ($5) or Developer ($12)?

## Key Files in Original Codebase
| File | Location | Purpose |
|------|----------|---------|
| `bot/` | PolyMarket/ | Full trading engine |
| `bot/.env` | PolyMarket/bot/ | Runtime secrets |
| `polymarket_credentials.json` | PolyMarket/ | API auth |
| `polymarket.db` | PolyMarket/ | 203MB market data |
| `nightly_sync.py` | PolyMarket/ | Data pipeline |
| `.mcp.json` | PolyMarket/ | MCP server config |
| `.gitignore` | PolyMarket/ | Git exclusions |
