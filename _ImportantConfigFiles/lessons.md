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

### 2026-05-23 — Codex Audit Found Spike Self-Block + Pending Duplicate Cascade
**What happened**: User ran ChatGPT Codex CLI parallel audit on a side-worktree (`codex/audit-fixes`). Codex applied 12-file diff + 2 migrations + REST cleanups, then exported the session. When vAI verified live state the next day, REST cleanups had reverted — 5 duplicate-waiting pending-signal groups and 4 zero-share Spike rows back in DB.

**Root causes Codex identified** (all real bugs vAI confirmed by reading the diffs):
1. **Spike `_open_position()` created tracker rows BEFORE any fill landed** — with `entry_size_shares=0`, `entry_size_usd=0`. Then `_get_open_position()` treated those zero-share rows as "already open" and refused to emit ladders. Bot silently stopped trading new Spike auctions.
2. **Pending-signal duplicate cascade** — `_insert_pending_signal` had no dedupe; every cycle re-inserted the same module/market/bracket/side row. Table grew, deferred signals never resolved cleanly.
3. **Pending signals could defer past auction close** — no cap on `wait_until` relative to auction end.
4. **Paper executor returned `unfilled` for resting limits; engine logged it as `executed`** — fantasy fills in the success log.
5. **Live order rejections dropped the exception reason** — only status changed to "rejected", no metadata.
6. **`Mid_Range_Spike` + `Big_Hold_Monthly` emitted `pct` while Spike builder expected `notional_usd`** — silent contract mismatch, ladder tiers were dropped.
7. **`fetch_all_active_trackings` defined twice in shared/polymarket.py** — second definition shadowed first.
8. **Kelly BUY gate at 0.01 (1%) silently dropped high-edge signals on auctions with 15-37 live brackets** — probability splits so finely that even good bets land at 0.2-0.5% kelly.

**Why the live cleanup reverted**: Codex applied REST UPDATEs but never deployed the code fixes. Master never received Codex's diff. Railway kept running old code that re-created the same broken rows next cycle.

**Rule**:
1. **REST cleanups are temporary unless the code that caused the bad rows is also deployed.** If you DELETE/UPDATE bad data without shipping the code fix, the bot re-creates the same garbage within minutes. Always pair data cleanup with code deploy, or skip the cleanup until code is live.
2. **Code review tool exports BEFORE trusting their claims.** Codex export said "duplicate groups remaining: 0" — vAI verified live and found 5. Tools can be wrong about durability of changes. Always re-query live state when picking up another agent's work.
3. **Don't create tracker rows before fills.** If a module needs an "open position" record, create it at fill time (in `position_manager.open_position`), never speculatively from the strategy code. Speculative rows + naive "is open" checks = self-block.
4. **Pending-signal table needs a unique partial index** on `(module_id, market_id, bracket, side) WHERE status='waiting'`. Without it, every insert path is a potential duplicate vector. Index = belt; app-side dedupe = suspenders. Both required.
5. **Strategy-contract changes (like Kelly gate 0.01→0.001) must be flagged loudly** in commits AND any session export. The Codex export did NOT mention this — vAI caught it only by reading the diff manually. New rule: any change to risk thresholds, position caps, or sizing constants must be in the export's executive summary AND require explicit Sir approval before merge.

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
