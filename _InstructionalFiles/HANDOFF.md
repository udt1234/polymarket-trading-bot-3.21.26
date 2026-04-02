# PolyMarket Bot — Handoff

## Current State (2026-04-01)
Full platform wired end-to-end. Module evaluates, risk checks run, paper trades execute, dashboard shows live data. Claude Code tooling (agents, skills, commands) fully configured.

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

## What's Next (Priority Order)
### Immediate
1. **Test the full loop** — restart servers, verify engine cycle runs end-to-end
2. **Add Slack webhook** — Settings > Notifications, paste webhook URL
3. **Deploy to Railway** — connect repo, set env vars, verify paper mode default

### Short-Term
4. **Test suite** — unit tests for signals, pacing, risk; integration tests for order lifecycle
5. **Google News RSS** — implement actual RSS parsing (currently scaffold)
6. **Backtest framework** — historical replay against resolved auctions with P&L reporting
7. **shadcn/ui polish** — install via CLI, replace raw HTML inputs

### Pre-Live Checklist (from Risk Audit 2026-04-01)
8. **FIX: Circuit breaker is dead** — `record_loss()`/`record_win()` never called from engine.py:130
9. **FIX: Spread check is no-op** — risk_manager.py:216 always returns True, needs real bid-ask spread
10. **FIX: Liquidity check is stub** — risk_manager.py:223 is empty, wire `depth_adjusted_size()`
11. **FIX: No global kill switch** — add `POST /api/engine/stop` to halt all trading
12. **FIX: Fail-open pattern** — 7x `except Exception: pass` in risk checks = DB outage disables safety
13. **FIX: Explicit order type** — add `"type": "GTC"` to executor.py:123 order dict
14. **Run @verify-bot** — end-to-end verification after above fixes
15. **Staging environment** — Railway preview deploy with paper mode
16. **Deployment freeze flag** — ENV var to block deploys during volatility

### Future Enhancements
13. **Recurring health checks** — `/loop` for position monitoring when live
14. **Git worktrees** — parallel Claude sessions for strategy/api/frontend work
15. **X API v2** — sub-second tweet detection for Elon module
16. **Kalman Filter** — adaptive noise filtering for count data
17. **PWA icons** — create 192/512px icons

## Login
- Email: darwin@xagency.com
- Password: PolyBot2026! (change after first login)
