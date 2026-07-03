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

### 2026-07-01 — Speed hot path: pre-sign between events, never compute or sign after the trigger
**What happened**: In the architecture diagram vAI drew the hot path as "tweet lands -> recompute fair value -> re-quote", which implies building and signing an order AFTER the trigger. Sir pushed back: weren't we going to keep multiple preset (pre-signed) limit bids ready so we cancel stale bids and fire already-built ones simultaneously? Yes, and that is faster.
**Root cause**: vAI put the expensive work (compute fair value + EIP-712 sign) ON the latency-critical path. Signing and recomputing after the event is dead weight when the plausible next states are knowable in advance.
**Rule**: On any speed hot path, never compute or sign after the trigger event. A continuous BACKGROUND loop (off the hot path, between events) pre-computes the target order set for the next plausible states and PRE-SIGNS it, refreshed every few seconds. The hot path then only (1) batch-cancels the now-stale resting orders and (2) submits the already-signed set. Caveat for Polymarket CLOB V2: the ms timestamp is baked in at signing, so pre-compute far ahead but sign as late as the staleness window allows and refresh the signed pool (open question: confirm that window). Also: stream every feed that offers one (tweets, book, our fills, on-chain settlement); poll only feeds with no stream (whale wallet, Gamma discovery). Auto-loaded rule at memory `lesson_presign_hotpath.md`.

### 2026-07-01 — Maker-only: never default a mispricing strategy to taking
**What happened**: While specing the S4 finish-line and S5 sweeper strategies, vAI recommended a "taker exception" to capture mispriced brackets. Sir corrected: the bot is maker-only, so why take? The right way to capture the exact same mispricing is to REST a post-only bid and let the seller cross to you.
**Root cause**: vAI framed "buy the mispriced bracket" and complete-set arb as taking (lifting an ask), when a resting maker bid captures it for zero fee (maker pays no exchange fee under CLOB V2) via FIFO queue priority. Taker fees also eat thin arbs, so taking is doubly wrong here.
**Rule**: On the maker-only bot, default EVERY mispricing / arb / sweep strategy to a resting post-only bid (maker, zero fee). Reserve "take" only for a genuine simultaneous complete-set arb, and even then verify the taker fee does not erase the margin. When describing "buy", state maker (rest a bid) vs taker (lift an ask) explicitly. Auto-loaded rule at memory `lesson_maker_not_taker.md`; constraint at `new_bot_maker_only.md`.

### 2026-06-29 — Look-ahead bias audit of every backtest
**What happened**: Reviewed our backtest suite against the 5 classic look-ahead leak patterns (an 80%-backtest that loses live = future data leaking into a decision). Read ~13 core scripts line by line.
**Findings**:
- CLEAN (walk-forward correct): trade_sim, finish_line_test, bracket_hit_backtest, calibration_test, market_pacing_test, seesaw_v3 (causal EMA), arb_test. The team consistently used `priors = [p for p in sel if p['e'] < s]` and built seasonal/hour profiles from posts before auction start. Our actionable conclusions (market beats models, finish-line/arb edges) are NOT leak artifacts.
- REAL LEAK (global_fit): accrual_model.py builds its share curve, and particle_filter.py its diurnal multiplier, on the WHOLE dataset including the future, then scores auctions inside that window. Inflates those two models' in-sample accuracy. Small magnitude (normalized shape) and harmless to the thesis (it only made models we already know lose to the market look slightly less bad), but it is the article's exact `scaler.fit(all_data)` bug.
- MILD: predictive_distribution + backtest_noovd_calibrated use leave-one-out (drops the test point but still uses future points). reversion_study conditions its "fadeable" subset on `burst_after(t)` (forward-looking), so that stat is not tradeable as-defined; single tiny window.
- No `center=True` anywhere.
**Root cause**: a parameter (curve/multiplier) fit once on all data and reused to score every auction is in-sample / look-ahead, even when the per-auction priors are correctly walk-forward.
**Rule**: Every backtest obeys the WALL: decide using only data with timestamp <= T; the outcome (winning_bucket / final count / resolution price) is for SCORING ONLY. Refit any curve/calibration/threshold walk-forward, never once on the full dataset. LOO is not walk-forward for live-accuracy claims. A backtest that looks too clean is suspect, not genius. Checklist co-located at `_DataMetricPulls/pacing_backtest/BACKTEST_RULES.md`; auto-loaded rule at memory `lesson_lookahead_bias.md`.

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

---

### 2026-06-24 — Alerter sells are LIMIT-ONLY (zero market orders, ever)
**What happened**: While designing the auction-end sell-sweep feature (`/sellnow`) and the position-flip sell-trigger buttons (Sell 25% / 50% / 100%), Sir reaffirmed that every sell-execution path in the Telegram alerter MUST use limit orders. ZERO market orders, full stop. This applies to the sweep, the per-bracket toggle, and any future auto-sell logic.

**Root cause**: It's tempting to reach for a "fast-exit market order" when the user wants speed, especially in the last hour of an auction. That instinct is wrong here: Polymarket order books for end-of-auction brackets are often thin, and a market order eats unbounded slippage. The bot project's non-negotiables already say "ALWAYS limit orders — NEVER market orders" — applying that to the alerter codepath was a clarification, not a new rule.

**Rules going forward**:
1. **Every `create_and_post_order` call in cloud_alerts/ must specify a `price` and use `OrderType.GTC` or `OrderType.FOK`.** Never `OrderType.MARKET`. Code reviews must reject any market-order codepath added to the alerter.
2. **Fast-fill strategy = LIMIT at top-of-book bid.** For each position to sell, read the order book, take the highest existing bid price, place a LIMIT sell AT that price. Crosses the spread → instant fill at that exact price → no slippage past it.
3. **Position size > top-of-book size → staircase.** Split into 2-3 limit orders at successively lower bid levels (e.g., 50% at best_bid, 30% at bid-1¢, 20% at bid-2¢). Still all limit, just at the next tiers down the book.
4. **Safety floor.** Refuse to place a sell if the computed limit price would be below $0.005, and notify Sir.
5. **Memory file:** `lesson_alerter_limit_orders_only.md` (auto-loaded; pointer in `MEMORY.md` under "Hard-won lessons").
