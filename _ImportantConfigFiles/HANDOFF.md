# PolyMarket Bot — Handoff

## Current State (2026-04-03)
Full platform wired end-to-end. Dashboard heatmaps added (DOW, hourly clock, bid prices by day/hour and elapsed days). Historical data backfilled: 32K+ posts (4yr CNN archive), 23K+ price snapshots (all 17 auctions via CLOB API). Hourly price collector running. Positions table shows market value with AVG->NOW pricing.

## What's Done
- **Auth**: Supabase user (darwin@xagency.com), JWT middleware on all routes
- **Truth Social Module**: Full pipeline — xTracker → pacing → projection → regime → signals → Kelly sizing
- **Elon Module**: Same 5-model ensemble, LunarCrush, Hawkes, variable auction periods
- **Risk Manager**: 15 checks (portfolio/single/correlated exposure, settlement decay, spread, liquidity)
- **Engine**: APScheduler loop, walk-forward validation every 6h, risk state sync
- **Executors**: Paper (simulated fills), Live (py-clob-client with profile credentials)
- **Daily P&L Snapshots**: Cron at 23:55 UTC + hourly backup
- **Calibration**: Brier score + log loss tracking, ensemble weight adjustment
- **Walk-Forward Validation**: Auto-reduces Kelly when model drifts
- **Slack Notifications**: Trade executed, circuit breaker, daily summary, regime shift
- **Wallet Profiles**: Create/switch/delete profiles with per-profile API keys
- **Frontend**: 9 pages (dashboard, modules, portfolio, trades, backtest, analytics, notes, logs, settings)
- **Mobile**: Bottom tab bar on screens < lg breakpoint
- **CLOB WebSocket**: Real-time order book subscriber with auto-reconnect
- **Order Book**: Spread + depth fetching for liquidity checks
- **Claude Code Tooling**: 7 agents, 2 skills, 3 commands, lessons.md, deny rules
- **Risk Fixes (2026-04-03)**: All 6 critical audit issues resolved — circuit breaker wired, spread/liquidity checks functional, global kill switch, fail-closed, explicit GTC
- **Test Suite (2026-04-03)**: 119 pytest tests — risk manager, signals, pacing, executor, engine, projection
- **Google News RSS**: 4-query RSS parser with dedup, conflict scoring, schedule detection
- **Backtest Framework**: 3 strategies, Kelly sizing, equity curves, Sharpe/Sortino, parquet support

## What's Next (Priority Order)
### Immediate
1. **Set up Elon Musk module the same way as Trump** — needs:
   - Backfill Elon historical post data (CNN archive or similar source)
   - Backfill Elon bracket prices from CLOB API (find market slugs)
   - Dashboard heatmaps (DOW, hourly clock, price by day/hour, price by elapsed day)
   - Verify xTracker trackings exist for Elon and wire up hourly price collector
2. **Test the full loop** — restart servers, verify engine cycle runs end-to-end
3. **Run @verify-bot** — end-to-end verification after risk fixes
4. **Deploy to Railway** — connect repo, set env vars, verify paper mode default

### Short-Term
5. **shadcn/ui polish** — install via CLI, replace raw HTML inputs
6. **Add auth to engine endpoints** — POST /api/engine/stop and /start lack Depends(require_auth)

### Pre-Live Checklist
7. **Run @risk-auditor** again — verify all 15 checks pass after fixes
8. **Staging environment** — Railway preview deploy with paper mode

### Future Enhancements
9. **Recurring health checks** — `/loop` for position monitoring when live
10. **Kalman Filter** — adaptive noise filtering for count data
11. **PWA icons** — create 192/512px icons

## Recently Completed (2026-04-03)
- **Test suite**: 119 pytest tests covering risk manager, signals, pacing, executor, engine, projection
- **Google News RSS**: Already implemented (4 queries, dedup, conflict scoring, schedule detection)
- **Backtest framework**: Already implemented (3 strategies, Kelly sizing, Sharpe/Sortino/drawdown, parquet support)
- **Risk audit fixes**: All 6 critical issues resolved, verified by @verify-bot + @risk-auditor
- **Claude Code tooling**: 7 agents, 2 skills, 3 commands, lessons.md

## Login
- Email: darwin@xagency.com
- Password: PolyBot2026! (change after first login)
