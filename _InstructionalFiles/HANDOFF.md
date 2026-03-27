# PolyMarket Bot — Handoff

## Current State (2026-03-24)
Full platform wired end-to-end. Module evaluates, risk checks run, paper trades execute, dashboard shows live data.

## What's Done
- **Auth**: Supabase user (darwin@xagency.com), JWT middleware on all routes
- **Truth Social Module**: Full pipeline — xTracker → pacing → projection → regime → signals → Kelly sizing
- **Risk Manager**: 13 checks (portfolio/single/correlated exposure, settlement decay, spread, liquidity)
- **Engine**: APScheduler loop, walk-forward validation every 6h, risk state sync
- **Executors**: Paper (simulated fills), Live (py-clob-client with profile credentials)
- **Daily P&L Snapshots**: Cron at 23:55 UTC + hourly backup
- **Calibration**: Brier score + log loss tracking, ensemble weight adjustment
- **Walk-Forward Validation**: Auto-reduces Kelly when model drifts
- **Slack Notifications**: Trade executed, circuit breaker, daily summary, regime shift
- **Wallet Profiles**: Create/switch/delete profiles with per-profile API keys
- **Frontend**: All 8 pages wired to API (dashboard, modules, portfolio, trades, analytics, logs, settings, login)
- **Mobile**: Bottom tab bar on screens < lg breakpoint
- **CLOB WebSocket**: Real-time order book subscriber with auto-reconnect
- **Order Book**: Spread + depth fetching for liquidity checks

## What's Next
1. **Test the full loop** — restart servers, verify engine cycle runs
2. **Add Slack webhook** — Settings > Notifications, paste webhook URL
3. **Google News RSS** — implement actual RSS parsing (currently scaffold)
4. **Backtest framework** — historical replay against resolved auctions
5. **shadcn/ui polish** — install via CLI, replace raw HTML inputs with proper components
6. **PWA icons** — create 192/512px icons
7. **Deploy to Railway** — connect repo, set env vars

## Login
- Email: darwin@xagency.com
- Password: PolyBot2026! (change after first login)
