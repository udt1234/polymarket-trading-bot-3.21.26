# PolyMarket Bot — Handoff

## Current State (2026-04-09)
Railway deployed (2 services online). QA/strategy review done — 8 critical bugs fixed and pushed. Dashboard filtering + reset + totals mismatch fixed.

## What's Done
- Everything from previous sessions (auth, modules, risk, engine, dashboard, etc.)
- **QA Fixes (2026-04-09)**: 8 bugs fixed — `cfg`->`mod_cfg`, missing order books for Elon, `resolved_at` in calibration, CORS, spread guard, platform detection
- **Railway Deploy**: API + Dashboard both online, auto-deploy from GitHub
- **Dev/Prod Split**: Local `.env` -> dev Supabase, Railway -> prod Supabase
- **Prod Schema Fix**: Added `metadata` column to signals + calibration_log tables
- **Profile Activate Fix**: Frontend was sending POST instead of PUT
- **Dashboard Fixes (2026-04-09)**:
  - `/metrics` endpoint now supports `module_id` and `days` params for scoped queries
  - Paper mode returns `wins`, `losses`, `closed_positions` consistently with live mode
  - `/portfolio/positions` and `/portfolio/exposure` now accept `module_id` filter
  - Module detail page filters positions by module_id (was fetching ALL)
  - Added `POST /api/settings/reset-paper-trades` endpoint (paper mode only)
  - Added "Reset Paper Trades" button in Settings > Trading Mode (with confirm step)

## What's Next (Priority Order)
### Short-Term
1. **Verify bot generates signals** — schema fix applied, confirm signals appear in Supabase
2. **Per-strategy P&L breakdown** — see results from different strategy configs
3. **Slack notifications not firing** — webhook URL may be stale, verify
4. **Notes page** — add strategy descriptions

## Railway URLs
- **Dashboard**: `polybot-dashboard.up.railway.app`
- **API**: `polymarket-trading-bot-32126-production.up.railway.app`
- **Railway project**: `railway.com/project/e9d87bab-d38a-42e3-b57a-f197c4b081cb`

## Supabase
- **Prod**: `xdonwowgqvmtrduikaon.supabase.co` (Railway uses this)
- **Dev**: `imqpwqzorrekvccvjkea.supabase.co` (local uses this)

## Login (both environments)
- Email: darwin@xagency.com
- Password: PolyBot2026!

## Local Dev
- Dashboard: `localhost:3010`
- API: `localhost:8010`
- Local `.env` points to dev Supabase (empty, safe to experiment)
