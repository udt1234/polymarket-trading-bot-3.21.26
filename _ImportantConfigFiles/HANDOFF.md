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
   - Backfill Elon historical post data (find X/Twitter archive source)
   - Backfill Elon bracket prices from CLOB API (find market slugs)
   - Dashboard heatmaps (DOW, hourly clock, price by day/hour, price by elapsed day)
   - Verify xTracker trackings exist for Elon and wire up hourly price collector
2. **Deploy to Railway** — connect repo, set env vars, verify paper mode default
3. **Remove Windows service after Railway deploy** — run `uninstall_service.bat` to delete the scheduled task

### Short-Term
4. **Update Notes page** — add strategy descriptions for all 5 ensemble models + 4 helpers
5. **shadcn/ui polish** — install via CLI, replace raw HTML inputs

### Pre-Live Checklist
6. **Run @risk-auditor** — verify all 15 checks pass
7. **Run @verify-bot** — end-to-end paper verification

## Windows Service (Local)
- **Install**: Run `install_service.bat` as admin — creates Windows Task Scheduler task "PolyBot" that auto-starts on login
- **Uninstall**: Run `uninstall_service.bat` — removes the scheduled task
- **Manual start**: Run `start_services.bat`
- **Logs**: `logs/api.log`, `logs/frontend.log`
- **Remove after Railway deploy** — no longer needed once running in cloud

## Recently Completed (2026-04-03)
- **Test suite**: 119 pytest tests covering risk manager, signals, pacing, executor, engine, projection
- **Google News RSS**: Already implemented (4 queries, dedup, conflict scoring, schedule detection)
- **Backtest framework**: Already implemented (3 strategies, Kelly sizing, Sharpe/Sortino/drawdown, parquet support)
- **Risk audit fixes**: All 6 critical issues resolved, verified by @verify-bot + @risk-auditor
- **Claude Code tooling**: 7 agents, 2 skills, 3 commands, lessons.md

## Login
- Email: darwin@xagency.com
- Password: PolyBot2026! (change after first login)
