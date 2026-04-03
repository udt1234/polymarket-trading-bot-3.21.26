# PolyMarket Bot — Handoff

## Current State (2026-04-03)
Full platform wired end-to-end. All 15 risk checks functional (no stubs). Order books fetched for spread/liquidity checks. Global kill switch added. Claude Code tooling (7 agents, 2 skills, 3 commands) fully configured.

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

## What's Next (Priority Order)
### Immediate
1. **Test the full loop** — restart servers, verify engine cycle runs end-to-end
2. **Run @verify-bot** — end-to-end verification after risk fixes
3. **Add Slack webhook** — Settings > Notifications, paste webhook URL
4. **Deploy to Railway** — connect repo, set env vars, verify paper mode default

### Short-Term
5. **Test suite** — unit tests for signals, pacing, risk; integration tests for order lifecycle
6. **Google News RSS** — implement actual RSS parsing (currently scaffold)
7. **Backtest framework** — historical replay against resolved auctions with P&L reporting
8. **shadcn/ui polish** — install via CLI, replace raw HTML inputs

### Pre-Live Checklist
9. **Run @risk-auditor** again — verify all 15 checks pass after fixes
10. **Staging environment** — Railway preview deploy with paper mode
11. **Deployment freeze flag** — ENV var to block deploys during volatility

### Future Enhancements
13. **Recurring health checks** — `/loop` for position monitoring when live
14. **Git worktrees** — parallel Claude sessions for strategy/api/frontend work
15. **X API v2** — sub-second tweet detection for Elon module
16. **Kalman Filter** — adaptive noise filtering for count data
17. **PWA icons** — create 192/512px icons

## Login
- Email: darwin@xagency.com
- Password: PolyBot2026! (change after first login)
