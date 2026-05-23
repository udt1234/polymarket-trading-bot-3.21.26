# PolyMarket Bot — Lessons Learned

Living mistake log. After every bug fix or correction, append a rule here.

## Format
```
### [DATE] — Short title
**What happened**: Description of the bug or mistake
**Root cause**: Why it happened
**Rule**: What to do differently going forward
```

---

### 2026-05-23 — Functional Audit Found 5 Live-Trade Blockers
**What happened**: 6-agent parallel functional audit found bot had been silently NOT trading on Railway for 24h. 100% of signals rejected with "risk state not synced — blocking until PnL data available". Plus 4 other blockers that would have caused real money loss the moment any module flipped to live.

**Root causes**:
1. `_sync_risk_state` flagged `_risk_synced=True` only on non-empty daily_pnl + successful query. On fresh deploys, Supabase hiccups, or any error path, it stayed False forever → silent reject on EVERY signal.
2. `LiveExecutor.execute()` wrote `status='filled'` + opened a position on CLOB POST acknowledgment. But CLOB POST = submission, NOT fill. Phantom inventory while real shares unmatched on book.
3. `MultiExecutor` fans Signal to N profiles in parallel. Each LiveExecutor called `open_position()` independently → N position rows for 1 signal.
4. Pending signals lost `token_id` + book fields on unlock. Rehydration only passed metadata dict.
5. No env-level live-trade backstop. Single Supabase row flip = live trading, no env confirmation.

**Rules**:
1. **Risk-state sync MUST be safe on empty/failed input.** Add `mark_synced_empty()` path that flips synced=True with zero PnL so loss caps evaluate against zero losses instead of blocking forever.
2. **Pre-warm critical state at engine boot, BEFORE first cycle fires.** Don't rely on the first cycle to also bootstrap state.
3. **CLOB POST != fill.** Write `status='submitted'` + store `clob_order_id`. Position opens on confirmed match via a future fill-poller.
4. **Persist EVERY field a downstream consumer needs on the pending row, then rehydrate on unlock.** Token_id, best_bid/ask, depth — all of it.
5. **Live trading must require BOTH module-level AND env-level opt-in.** `ALLOW_LIVE_TRADING=true` env backstop. Default False.
6. **Silent-no-trade is the worst failure mode.** CI passed. Logs looked healthy. Bot looked alive. Add "trade count per hour" Slack alert that fires if zero for >2h.

---

### 2026-05-02 — Trump Module Stopped Trading 4 Days (Missing pending_signals Table)
**What happened**: Bot's Trump module ran 5-min cycles, logs showed "signals=4" per cycle, but no trades executed for 4 days. No risk-rejection logs, no execution logs — all silent.
**Root cause**: Migration 006 (`pending_signals` table) was never applied to prod Supabase. The Wait-for-Dip feature (`wait_for_dip_enabled=true` in module config) calls `_insert_pending_signal()` which has its OWN inner try/except. That inner block swallowed the "relation pending_signals does not exist" error silently. The OUTER `_maybe_defer_signal` then returned `True` (deferred) for every signal — and the engine skipped them from risk_manager.execute(). The function was supposed to fail-closed (return False so signals continue) but instead failed-open (return True = deferred = dropped on the floor).
**Rule**:
1. **Apply ALL pending migrations** as part of the deploy checklist. Maintain a `migrations_applied` checklist in HANDOFF.md or run `supabase db push` from CI.
2. **Don't nest try/except in skip-decision functions**. If a function returns bool (skip vs proceed), failures inside it must propagate to the outer logic so we can log + decide. Inner swallow → outer wrong-decision is an undebuggable failure mode.
3. **Add a `signals_deferred=N` count to the Cycle log line** so deferred signals are visible alongside `signals=N` (rather than just lumped in with "generated").
4. **Add a runtime self-check on engine boot** that pings each table the engine writes to (positions, trades, signals, pending_signals, logs, post_count_snapshots, daily_pnl) and refuses to start if any is missing. Fail loud at boot, not silent at runtime.

---

### 2026-04-01 — Risk Auditor Found 6 Critical Issues
**What happened**: First full risk audit revealed 3 UNSAFE checks and 3 partially safe.
**Root cause**: Checks were scaffolded but never wired to live data or execution flow.
**Issues found**:
1. Circuit breaker `record_loss()`/`record_win()` never called from engine — breaker is dead code
2. Spread check always returns True — `pass` in rejection branch, uses edge not bid-ask spread
3. Liquidity check is empty stub — `depth_adjusted_size()` exists but never called
4. No global kill switch — only per-module kill, no `POST /api/engine/stop`
5. 7x `except Exception: pass` in risk_manager.py = fail-open on DB errors
6. Order type relies on py-clob-client default — no explicit `type: "GTC"`
**Rule**: Before going live, ALL 15 risk checks must be verified as functional by @risk-auditor. No stubs allowed.

### 2026-04-03 — All 6 Risk Issues Fixed
**What happened**: Implemented all fixes from the 2026-04-01 audit.
**Changes made**:
1. Circuit breaker wired — `record_loss()`/`record_win()` called from `resolution_tracker.py` on position close
2. Spread check — now uses real bid-ask spread from order book, rejects if > slippage_tolerance
3. Liquidity check — now checks order book depth, rejects if order > 30% of available depth
4. Global kill switch — `POST /api/engine/stop` stops engine + closes all positions + logs
5. Fail-closed — all 7 `except Exception: pass` in risk checks now return `False` with error message
6. Explicit GTC — `"type": "GTC"` added to `create_and_post_order` call
7. Signal dataclass — added `best_bid`, `best_ask`, `bid_depth_5`, `ask_depth_5` fields
8. Module — fetches order books for top brackets and passes data to signals
**Rule**: Never scaffold a risk check as a stub. If it can't be implemented yet, it must return False (fail-closed), not True.

### Rules Derived from Architecture Decisions
1. **Always use noon-to-noon boundaries** — xTracker auctions start/end at noon ET, not midnight. Off-by-12h errors silently corrupt projections.
2. **Dedup hourly rows before counting** — Overlapping Tue-Tue and Fri-Fri trackings return the same hours twice. Key = `YYYY-MM-DD|HH`, keep higher count.
3. **CLOB midpoints over Gamma prices** — Gamma prices lag. Use CLOB mid for edge calculation, Gamma as fallback only.
4. **ALWAYS use limit orders, never market orders** — Market orders on Polymarket have unbounded slippage. Every order placement must specify a price. No exceptions.
5. **ENV=production guard before any live execution** — Paper mode is default. Live executor must check `PAPER_MODE != true` before submitting to CLOB.
6. **Rate limit all external APIs** — 300ms between xTracker, 500ms between Gamma, 1s between CLOB history. Bursting gets IP banned.
7. **Google SA key was exposed in early session** — Rotated. Never put credentials in .md files, committed code, or .mcp.json.

### 2026-05-02 — Healthcheck endpoint silently broken by auth requirement
**What happened**: PR #18 added `Depends(require_auth)` to every /api/engine/* route. Railway's `healthcheckPath` in railway.toml was `/api/engine/status` — now returned 401 unauthenticated. Healthcheck failed every deploy from that PR forward. Railway kept the previous-good container running and refused to promote new deploys. **7 subsequent PRs (#21–#28) appeared to merge cleanly but never reached production for ~5 days.**
**Root cause**: I checked Railway showed "Online" but didn't open the deploy history to confirm the latest commit was the active one. Bot continued running pre-#18 code, dashboard kept rendering, no user-visible smoking gun.
**Rules going forward**:
1. Healthcheck endpoints MUST remain unauthenticated. Dedicated `/api/healthz` (or similar), never gated behind auth.
2. After EVERY merge, check Railway's deploy history — confirm the new commit shows ACTIVE (not just "Online"). The service can be Online while running stale code.
3. Any PR touching `api/main.py` route definitions or `railway.toml` healthcheck config requires explicit verification that the healthcheck path returns 200 unauthenticated.
4. If a healthcheck path needs sensitive data, split it: lightweight `/healthz` for the load balancer, full `/status` behind auth for humans.
