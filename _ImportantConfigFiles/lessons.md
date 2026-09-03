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

### 2026-09-01 — An upstream FORMAT change silences a module without erroring; assert on OUTPUT, not liveness
**What happened**: Nightly QA found 4 of 7 paper modules emitting zero signals and the whole bot showing zero fills for 12 days, while the engine cycled every 5 minutes, the watchdog logged "all healthy" 94 times, and every module row stayed `status='paper'` with `inactive_reason=null`. Five separate causes, none of which raised anything. (1) Polymarket started appending a year to tweet slugs (`elon-musk-of-tweets-august-31-september-2-2026`); `parse_slug_window`'s regex was anchored on the second day number, so EVERY current slug parsed to `None` and S2 Basket-Hold + Copytrader found no live auction from 2026-08-21 on. (2) `elon_reversion` and `elon_late_arb` passed `slug_contains` to Gamma `/events`, which does not support that parameter — it was silently ignored, so both modules had been scanning Belgian soccer-corner and crypto up/down events since the day they were created on 2026-07-24, and had never emitted one signal. (3) `elon_late_arb` shipped complement-pair legs with `spread/best_bid/best_ask = None`, which the risk gate fails closed on. (4) Market Maker quoted mid-minus-2c into 1c-wide Elon books, resting under the best bid: 33 approved quotes, 0 fills, 1,771 duplicate-order rejects per day. (5) `arb_scanner` had no exit path and no per-leg cap, so it re-bought the same orphaned leg every cycle until four legs compounded to ~$100 each and pinned its $500 budget for 39 days. Separately, 8,448 SELL orders had been resting up to 53 days because the stale-order sweep filtered on `side='BUY'`.
**Root cause**: Every failure was a SILENT one. An unsupported query parameter returns 200 with the wrong data. A regex that stops matching returns `None`, not an error. A quote that can never fill is indistinguishable from a quote that has not filled yet. The health model asked "is the module running?" when the only question that matters is "is it producing anything?" — the exact blind spot already written up on 2026-07-21, unfixed for the new failure shapes.
**Rule**: (a) NEVER trust a third-party filter parameter you have not verified returns filtered data — call it once and assert the result actually matches the filter; `slug_contains` cost two modules six weeks. (b) Any parser of an upstream-controlled STRING (slug, ticker, filename) gets a regression test with a REAL current sample, and must tolerate additive suffixes; treat a parser returning `None` for 100% of live inputs as a P1, not as "no data". (c) A module that emits zero signals for longer than its natural cadence is BROKEN until proven idle — the watchdog must assert on signals/fills produced, not on cycles completed, and must alert per module. (d) A maker quote that is approved but never fills is a dead quote: alert on approved-with-no-fill, and gate quoting on the book actually being wide enough to capture. (e) Any accumulate-only path (positions, resting orders) needs both an exit and a cap; sweeps must cover BOTH sides. (f) When a module is silent, run its `evaluate()` locally against live APIs and print the gate it dies at — five root causes fell out in one pass and none were visible from the database.

### 2026-08-27 — QA a pipeline for row-SET completeness, not just value accuracy
**What happened**: MyPolyTracker showed the WRONG Elon auction — Aug25-Sep1 (24 posts) instead of the actionable Aug21-28 (157 posts, ending in 23h that the user was actively looking at on Polymarket). Every handle was affected. Earlier the same session I ran a "QA" that confirmed counts were accurate (Trump 55=55) and declared the data correct. The user caught the real problem live: the most important auction for every handle was simply MISSING from Supabase.
**Root cause**: Two layers. (1) The data bug: xTracker's `/trackings` API returns `marketLink: null` on the current near-resolution auction for every handle, and the poller had `if not marketLink: continue`, silently dropping exactly the auctions that matter most. (2) The QA blind spot: my QA checked VALUE accuracy (do the stored numbers match the source) but never checked SET completeness (is every expected auction present). A silently-dropped record passes every value-accuracy check, so the miss slid through and shipped.
**Rule**: QA every data pipeline on two axes, always: (a) VALUES — stored numbers match the source; (b) COMPLETENESS — every expected record is present. For the tracker specifically, cross-check the SET of live/recent auctions in Supabase against xTracker trackings per handle (row counts), not just the counts on the rows that exist. Treat any `continue`/skip in an ingest loop as data-loss: log what was skipped and why — silent skips read as "covered everything." When a value looks wrong, first ask "is the right RECORD even here?" before trusting the one that is. xTracker leaves `marketLink=null` on the current auction; derive the slug from handle-prefix + window (`poll.py derive_slug`), never drop it.
---

### 2026-07-30 - Canonical prices was missing the WINNING bracket for 55% of Elon auctions; a repair script erased the warning
**What happened**: @backtest-auditor, auditing `pattern_discovery_2026-07-26.py`, found that most Elon auctions had no price rows for the bracket that actually won. Measured across the whole canonical layer: winner-bracket price coverage was **109/243 (44.9%) for Elon** and **54/54 (100%) for Trump**. The study defaulted the missing winner's market probability to `1e-6` instead of excluding the auction, which fabricated the market's log loss and produced the headline "naive extrapolation beats the market" at +3.3350 skill. Excluding inadmissible auctions flipped it to -0.3722, i.e. the market wins, which is what the clean Trump control had been saying all along.

**Root cause**: three defects compounding, none of them the suspected bucket-label mismatch. The `winning_bucket` labels and token ids in `auctions` were correct the whole time.
1. **Late-added brackets were never pulled.** Polymarket extends the bracket ladder mid-auction as the count moves. `10_fresh_gamma_rebuild.py` took its bracket list from a cached Gamma events snapshot, so brackets added after that snapshot were never fetched. The winner is disproportionately a late-added bracket precisely because it is the one the count moved toward. 91 auctions had zero raw trades for the winner.
2. **Prices was left stale after a raw repair.** `11_recover_demoted_auctions.py` / `12_recover_v2.py` appended recovered brackets into `_raw_imports/api_trades_v2/`, but nobody re-ran `04_build_prices.py`. `prices` is derived, so 43 auctions had the winner in raw and still no price row. Those pulls were also truncated at exactly 3500 rows (7 x the 500-row page), and data-api returns newest-first, so even the "recovered" brackets were missing the START of the auction.
3. **The repair script erased the only warning.** `08_normalize_bucket_labels.py` correctly demoted all 134 affected auctions to `confidence='low'` + `..._bracket_mismatch`. `13_refresh_gamma_resolutions.py` then set `confidence='high'` for every auction where Gamma confirmed a single YES winner, with no check that the winner had price rows. Knowing WHO won is not the same as HAVING market data for them. That upgrade is what let the auctions back through the documented `confidence in ('high','medium')` filter. `07_consistency_test.py` check 5 detected the condition correctly but reported it as WARN, in a Google Sheet, with a zero exit code, so nobody saw it for six months.

Trump was unaffected only because its 7-day markets ship a stable bracket set that the original pull captured whole.

A fourth, latent defect surfaced during the rebuild: `prices.bucket` carried Polymarket's raw labels, which mix en-dash and hyphen (`100–124` vs `100-124`), while `auctions.winning_bucket` is hyphenated. `08_normalize_bucket_labels.py` had patched the prices files in place once, so any rebuild silently reintroduced 163 mismatched Elon labels. This is the label-mismatch the original hypothesis suspected; it was real, but it was a second bug, not the cause of the coverage gap. Normalization now happens inside `03`/`04` at build time, so a rebuild is correct on its own.

**Outcome**: 120 auctions repaired, 4.17M trade rows recovered, prices rebuilt. Winner coverage went **Elon 44.9% -> 100.0% (243/243)**, Trump held at 100.0% (54/54). Nine brackets across 4 auctions (3 Elon Sept-2025 point markets, 1 Trump) are genuinely absent from data-api and are documented as a data-availability limit, not a bug; none of them is a winner.

**Rule**:
1. **A derived table must be rebuilt whenever its source changes.** Any script that writes to `_raw_imports/` must be followed by `04_build_prices.py`. Never leave `prices` stale.
2. **Never upgrade a confidence flag past what the data supports.** Resolving *who won* from Gamma does not conjure *market data* for them. `13` now grants `confidence='high'` only when prices actually covers the winner, and otherwise tags `_no_winner_price`.
3. **A data-integrity check that cannot fail a build is not a check.** Check 5 was WARN-only; it is now FAIL, and `07_consistency_test.py` exits non-zero. `04_build_prices.py` prints winner coverage at the end of every build and `15_verify_winner_coverage.py` exits 1 below a 95% floor.
4. **A count that is an exact multiple of the page size is a truncated pull, not a complete one.** Verify against the API before trusting it.
5. **EXCLUDE, never default.** If the winning bracket has no price at time T, that auction is inadmissible for any model-vs-market comparison. Substituting `1e-6`/epsilon/uniform fabricates the market's score and inverts the result. A market baseline that a naive model beats is a coverage bug, not a discovery.
6. **Normalize labels at the derived layer, not in a one-off patch pass.** A fix that edits output files in place is undone by the next rebuild. `03`/`04` now normalize en-dash to hyphen while building.
7. **Coverage is per-checkpoint, not per-auction.** Passing the coverage gate only means the winner is priced *somewhere*. Polymarket extends the bracket ladder mid-flight, so on 134 auctions the winning bracket did not exist when the auction opened (Elon 7-day: median lag 1h but p90 169h, max 235h). A checkpoint at T before `winner_first_hour_utc` still has no market view of the winner. Join `canonical/_audit/winner_admissibility.csv` and drop those checkpoints.
8. Repair tooling: `14_repair_bracket_coverage.py` (re-derives the bracket set from a fresh Gamma pull and fetches anything absent or truncated) then `04_build_prices.py` then `15_verify_winner_coverage.py`. Full evidence: `_DataMetricPulls/pacing_backtest/audits/pattern_discovery_2026-07-26.md`.

---

### 2026-07-03 - Append-forever parquet merges OOM; partition by day
**What happened**: The daily `PolymarketRecorderPull` task silently grew one parquet per series since Jun 23. The merge step loaded the whole existing file + concat in pandas; at 87M rows (elon-tweets-48h) it crashed with a 3.26 GiB allocation error, exit code 1.
**Root cause**: Unbounded append design: every run re-read the entire history into memory to add one day of data. Works at week one, guaranteed OOM later.
**Rule**: Any recurring merge job must have bounded memory per run. Recorder layout is now `{series}.parquet/` as a DIRECTORY of `{YYYYMMDD}.parquet` day files: merges touch one day only, `pd.read_parquet(dir)` still reads the whole dataset, `l2_history._files()` globs one level deeper. Never design an append job that re-reads its full history.

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

### [2026-07-11] — Bot read $0 collateral: funds were in the new Deposit Wallet (sig_type 3), not the old proxy
**What happened:** Bot reported $0 spendable collateral while the Polymarket UI showed $921.74 on wallet `0xD0f99f553...d400`. A 5-agent on-chain investigation (owner check, CREATE2 proxy derivation, balance sweep, data-API, architecture research) proved: the signer key `0xbB82...18db` controls BOTH the old `1proxy` `0xD0f99f...d400` (signature_type 1) AND a new Deposit Wallet `0xE83C02...04Ce` (signature_type 3). The old proxy is EMPTY on-chain ($0 of every token); the $921.737394 sits at the Deposit Wallet as **pUSD** (`0xC011a7E1...`), with unlimited allowances to the V2 exchanges already set.
**Root cause:** Polymarket's **2026-04-28 CLOB V2 migration** moved collateral to pUSD and routed deposits to a new per-user Deposit Wallet (ERC-1967 proxy, sig_type 3). The bot's `POLYMARKET_WALLET_ADDRESS` still pointed at the pre-migration proxy, so it correctly read $0 for a wallet that genuinely holds nothing. Right key, wrong wallet. On-chain USDC/USDC.e greps also show $0 because collateral is pUSD now (a different token).
**Fix:** Set `POLYMARKET_WALLET_ADDRESS=0xE83C02Ddb322E408b686fe133B509235f46B04Ce` on Dublin (or leave it empty so `SecureClient.create(private_key=...)` defaults to the Deposit Wallet). `get_collateral_balance()` then read 921.737394 pUSD. Rule: if the bot ever reads $0 collateral, it's pointed at the wrong wallet — derive the Deposit Wallet via the SDK (no `wallet=` arg) and repoint. Memory: `memory/lesson_deposit_wallet_sig3.md`.

### [2026-07-26]: @backtest-builder builds, @backtest-auditor audits. Never hand-write a backtest.
**What happened:** The user asked for machine-learning pattern discovery on the Elon post-count history. vAI scoped the analysis, ran only descriptive statistics (quantiles, autocorrelation, variance decomposition), and then proposed hand-writing the discovery script itself. `@backtest-builder` was mentioned only at the end, as a patch for the "vAI would be marking vAI's own homework" problem. The user pushed back: "if i have a backtest auditor agent, why would u go and build it? Shouldnt that be the default?" and instructed that the builder is always the default for building, the auditor always the default for auditing, and that the acting agent must be named explicitly going forward.
**Root cause:** vAI treated the two purpose-built agents as an optional escalation rather than the primary path. Hand-rolling felt faster, so the agents got demoted to a footnote. Two costs: the agents the user paid to have built went unused, and vAI ended up as both producer and validator of the same result, which is precisely the arrangement the user has said they do not trust. vAI also never stated who was doing the work, so the user could not tell whether a number came from vAI or from a specialist.
**Related:** the same session established that all prior strategy conclusions are demoted to HISTORY (unverified) and may never be used to skip work. See `memory/feedback_distrust_past_findings.md`.
**Rule:**
1. Any request meaning backtest, simulate, what if, test this strategy, find patterns in the history, or measure this model routes to `@backtest-builder` FIRST. vAI does not write the script.
2. Every builder output goes to `@backtest-auditor` before a number is quoted, a model is locked, or a param is changed. No exceptions, including negative results.
3. This covers forecast-accuracy and calibration studies too, not just P&L. The auditor scope-gates the diagnostic case (`.claude/agents/backtest-auditor.md` line 13).
4. Say it out loud every time: "invoking @backtest-builder to build X", "invoking @backtest-auditor to audit X". Attribute every reported number to the agent that produced it.
5. Only exception, and it must be stated when used: a one-line throwaway probe (row count, date range, column check). The moment it fits a model, splits train/test, or produces a number the user might act on, it goes to the builder.
6. vAI's role is scoping the question, pre-registering the rule list and held-out span, relaying the verdict, and recommending the next move.
**Enforced in:** `CLAUDE.md` section "Backtest Agents Are The Default" plus rule 6 under "Rules for new backtests"; `memory/feedback_builder_auditor_default.md` with a pointer in `memory/MEMORY.md`.

### [2026-07-26] — Weather reward-farm: mark-out choice decided the verdict, and 93% of the reward leg was an assumption
**What happened:** Ran the reward-farm ("rent the book") replay on 3.6 days of our own recorded weather-market L2 (100.3M rows, 348 markets, 105.8 market-days). The gross thesis validated cleanly: weather books are so thin that a 2,500-share quote 1c off mid captures a mean 0.90 of the reward pool (~$87/market-day), exactly as the earlier Gamma scan predicted. But the NET was negative in all 225 swept configurations, and two modelling decisions turned out to carry the whole answer.
**Root cause 1 — mark-out horizon vs achievable exit.** The standard 60-second MID mark-out showed a clean edge: +$32.11/market-day, bootstrap P(<=0)=0.0%. The median weather market spread is 25.1c, so a mid exit is fiction. Repricing the exit at the touch (long out into the bid, short out into the ask) flipped the identical config to -$51.39/market-day, P(<=0)=100%. A mid mark-out silently gifts you half the spread on every unwind.
**Root cause 2 — a live-only API field.** Gamma zeroes `rewardsDailyRate` when a market closes, so only 24 of 348 markets still had their real pool and the other 324 used a $100/day floor (the recorder's own subscription threshold). Reward income is linear in that rate. @backtest-auditor returned FAIL on exactly this: at $100 the best config is -$3.64/market-day, at $233 (inside the live observed range) it is +$0.41. The sign was undetermined by the data.
**Rule:**
1. In any maker backtest compute three mark-outs — mid, touch, resolution — and headline the TOUCH. Print the spread distribution first; if the median spread exceeds ~2x your quote distance, the mid is not an exit and a mid mark-out is invalid.
2. Watch for a strategy that scores best where the book is widest — that is scoring on inventory it cannot escape. On weather, pool share and exitability moved in opposite directions (share 0.60 at a 25c spread, 0.04 at <=5c). No window had both.
3. When a parameter had to be assumed, never report a point estimate. Report the BREAKEVEN value and how much of the live observed distribution clears it. Here: breakeven ~$130-145/day/bracket, live median $114, only 5/20 brackets clear $129. That converts an unanswerable number into a decision.
4. Recorders must persist the VALUES of the API fields they filter on, not just the pass/fail. Fixed locally in `polymarket-weather-recorder` (`discover()` returns a `ratemap`; `dump_tokenmap()` writes rate/max_spread/min_size) — NOT yet deployed.
**Verdict:** NO-GO on committing capital to weather reward-farming. Only surviving variant is min-size (100-share) quotes 2.5-3.0c off mid with a jump-cancel defense, restricted to brackets whose live pool >= ~$150/day (~3 of 20), worth ~$50-100/day — inside the noise of a 3.6-day sample. Better target: a family whose pool clears breakeven by a wide margin (Fed decisions ~$1,250/day).
**Artifacts:** `_DataMetricPulls/pacing_backtest/weather_reward_farm_replay.py`, `weather_reward_farm_report.py`, `weather_partition_by_slug.py`, results in `audit_out_weather_v2/`, audit log `audits/weather_reward_farm_replay_2026-07-26.md`. Memory: `reward_farm_verified.md`, `lesson_markout_to_touch_not_mid.md`, `lesson_persist_live_only_fields.md`.

### [2026-07-29]: Pattern discovery: a defaulted market price inverted the headline, and a tiny-n CI manufactured a second fake win
**What happened:** Ran the pre-registered ML pattern-discovery study on Elon + Trump posting cadence (7 methods, 4 baselines, walk-forward wall fixed before any sealed data was opened). Built by `@backtest-builder`, audited FOUR times by `@backtest-auditor`: FAIL -> WARN -> WARN -> PASS. Two separate fake positives had to be killed on the way, plus a third real bug in a model.

**Bug 1 (FATAL, the headline inverter):** `market_bracket_probs()` built the market's distribution only over brackets that had a price, and its own docstring promised the caller would filter auctions on winner coverage. That filter was never written. `_emit()` instead defaulted any unpriced bracket to `1e-6` probability, INCLUDING THE WINNER, and the scorer then computed `-log(1e-6)` against it. Because 63.6% of Elon 2-day and 78.2% of Elon 7-day winning brackets have no price data at all, the market's log loss was fabricated on exactly the outcome that decides the score. Reported headline: "naive extrapolation beats the market, +3.3350 skill". Corrected by excluding inadmissible auctions: **-0.3722, market beats naive.** The sign flipped. Trump 7-day, the 0%-missing control, had correctly said nothing beats the market all along, and that contrast was the tell.

**Bug 2 (a real model bug, not a weak model):** the Hawkes thinning simulator (`_hawkes_thin_sim`) decayed its self-excitation accumulator only on ACCEPTED candidates, leaving it frozen across rejected ones while simulated time advanced. The intensity bound stayed inflated and the sim ran away: mean simulated final 1516 against a true 77, roughly 20x hot, which fully explained its 12-nat log loss. The burst hypothesis had never actually been tested until this was fixed.

**Bug 3 (the second fake win):** after splitting a shared RNG (a nominally cosmetic fix), `elon_7day beats market` flipped from "none" to the composed Hawkes model. The auditor exhaustively enumerated all 27 bootstrap resamples of its 3 admissible auctions and proved the CI **cannot** include zero once all three per-auction values share a sign. "CI excludes zero" at n=3 is a 25% base rate under a true null, not 5%. Drop-best jackknife collapsed +0.2597 to +0.0109. A ~0.009 shift in one CI bound, from a seed change, had flipped the verdict.

**Root cause (all three):** the harness was right and the comparator was wrong. Every leak check that this project has built (THE WALL, noon-ET slug parsing, locked_pace import, held-out re-score) passed on the first audit. What failed was (a) substituting a floor value for missing data instead of excluding the row, (b) an unvalidated simulator, and (c) a success flag with no minimum-n gate. None of these throw an error; all three produce a beautiful number.

**Rules:**
1. **EXCLUDE, never default.** A missing market price on the winning bracket makes that (auction, checkpoint) inadmissible for any model-vs-market comparison. Never substitute `1e-6`, epsilon, or uniform. Report admissible n separately from full n, and never print a bare "n" a reader could confuse for the comparison sample.
2. **A naive baseline beating a real prediction market is a bug, not a discovery.** Treat any impossibly-good baseline as a coverage or scoring defect and hunt it before celebrating.
3. **Hard-gate success flags on n in the MACHINE-READABLE output, not in prose.** Below 10 resolved auctions, emit a disqualifying sentinel, never a method name. The same file had a correct "too thin to call" paragraph AND a flag saying it won; the flag is what gets read. See `memory/lesson_tiny_n_ci_degenerate.md`.
4. **A newly appearing positive on the thinnest cell after a refactor or reseed is the most likely lie in the report.** Diff the affected columns and attribute the change before believing it.
5. **Validate a stochastic simulator against a known case before trusting its score.** A model reported as "loses badly" may be broken rather than wrong, which means the hypothesis was never tested.
6. **Give every stochastic method its own seeded generator.** A shared global RNG means fixing one method silently perturbs every other, which destroys single-method diff audits.

**The result (audited, reproduced from `per_row.csv` independently):** real forecasting skill vs naive EXISTS (HMM/mood-states +0.121 CI[+0.029,+0.206] on 87 sealed Elon days), adds NOTHING over the LOCKED `locked_pace` ensemble (every method's CI straddles zero, which validates the locked model), and beats the market NOWHERE measurable (Elon 2-day n=19, Trump 7-day n=20, both "none"). OPEN QUESTION, explicitly not a finding: on the 9 Elon 2-day auctions the market never priced, `locked_pace` beats naive +0.318 CI[+0.089,+0.558] and those auctions are HARDER not easier (naive log loss 1.698 vs 1.121), but every fitted method there is unproven at n=9 and Elon 7-day's 16 excluded auctions show the opposite. Untestable for tradeability without a market price. Deciding test: were those brackets never TRADED (dead, no counterparty for a resting maker quote) or merely never RECORDED (the live L2 recorder can answer it on recent auctions)?

**Artifacts:** prereg `_DataMetricPulls/pacing_backtest/prereg/pattern_discovery_2026-07-26.md`; scripts `pattern_discovery_2026-07-26.py`, `pattern_discovery_lib.py`, `pattern_discovery_methods.py`; outputs `pattern_discovery_out/` (`per_row.csv`, `summary.md`, RUN_META, trial_count 125); audit logs `audits/pattern_discovery_2026-07-26{,_reaudit,_reaudit2,_reaudit3}.md`. Memory: `pattern_discovery_result_2026_07_29.md`, `lesson_tiny_n_ci_degenerate.md`, `lesson_canonical_token_gaps.md` (updated with the real 63.6%/78.2% coverage figures).
