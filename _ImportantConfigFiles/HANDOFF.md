# PolyMarket Bot — Handoff

## 🚧 BUILD PROGRESS (PART J of BUILD_SPEC.md) — updated 2026-07-06
All on branch `feat/newbot-step1-skeleton` (steps 1-6, one commit each). Migrations 022 (orders lifecycle) + 023 (positions 'closing') APPLIED to prod Supabase.
- **Step 1 Skeleton: DONE** — boot + registry + unauth healthz. ACCEPT PASS.
- **Step 2 Execution core: DONE, ACCEPT PASS 2026-07-06 from the Dublin VPS** — post-only rested, user-WS PLACEMENT + CANCELLATION captured, clean cancel, orders row lifecycle correct. CRITICAL SDK SWAP: py_clob_client is ARCHIVED (orders rejected 'invalid order version'); execution now runs on the official `polymarket-client` SDK (SecureClient, derived creds, GTD >= 3min, heartbeat dormant/opt-in). See memory `lesson_polymarket_client_sdk`.
- **Step 3 Data + brain: DONE** — discovery (tag 972), slug noon-ET windows, xTracker count, Gamma-Poisson projection, bracket distribution. ACCEPT PASS live (6 auctions, sum=1, impossible=0).
- **Step 4 S2 + Copytrader (paper): DONE** — fail-closed risk gate, aggregate price ceiling, paper maker fills, positions + accumulating realized P&L, 5-min engine. ACCEPT PASS live (2 S2 signals approved + rested; simulated dip filled; P&L exact). Copytrader = Option B, whale 0xd218e474...5c9 verified active ($473k).
- **Step 5 Speed: CODE DONE, acceptance GATED** — tweet_stream.py (needs TWITTERAPI_IO_KEY + verified WS URL), pre-sign loop (20s refresh) + hot path (batch cancel + pre-signed POST). SDK already keeps a warm http2 client.
- **Step 6 Observability + safety: DONE** — breaker (persisted, trips on 5 losses, fail-closed read), Telegram heartbeat (delivered ✓), per-module /api/engine/health, kill-switch CLI (pause / cancel-all only). ACCEPT PASS.
- **🟢 DUBLIN VPS LIVE (2026-07-06):** EC2 `i-05a8f18c02960b74f` (polybot-dublin), eu-west-1, t3.small, Ubuntu 24.04, IP `34.245.42.217`. SSH: `ssh -i ~/.ssh/polybot_dublin polybot@34.245.42.217`. systemd service `polybot` (uvicorn api.main:app :8000), UTC+chrony, UFW SSH-only from Sir's IP. **PAPER TRADING RUNNING 24/7** — S2 resting paper quotes on the live 2-day auction; order placement from this box VERIFIED (geoblock cleared). Deploy updates: git push -> ssh git pull -> systemctl restart polybot.
- **🟢 DASHBOARD LIVE (2026-07-08):** https://polybot-web-production-8f5a.up.railway.app — Railway project `polybot-dashboard` (id 2a6bf784-b716-4dd0-ab74-9cdf87577dd7), service `polybot-web`, deploys from `web/` (branch feat/newbot-step1-skeleton). Password-gated (SHA-256 cookie; `DASHBOARD_PASSWORD` env + URL in `~/.credentials/shared.env`). Reads Supabase only; health derived from cycle-log freshness + 24h trades (bot API is firewalled, no HTTP). Has a Fills Tape (trades in/out), positions, resting orders, price chart, signals. Fixed a Next fetch-cache freeze that faked "engine stale" (memory `lesson_next_fetch_cache_stale_dashboard`). Redeploy: `cd web && railway up`.
- **🟢 WATCHDOG LIVE (2026-07-08):** Railway service `polybot-watchdog` (same project), from `infra/watchdog/`. Pure-httpx always-on loop polling Supabase every 10m; Telegram alerts on engine-stale (>15m no cycle) / module-down / breaker-trip / error-spike, edge-triggered with de-dup + recovery (state in settings row `watchdog_state`). External to the Dublin bot so it fires even if the bot dies. Redeploy: `cd infra/watchdog && railway up`.
- **Copytrader fix (2026-07-08):** ROI gate now scores the whale's live book (was filtering `/positions` for size==0 closed trades that endpoint never returns -> benched forever). Verified: whale healthy 128%, trades on tweet-market overlap, logs "idle by design" when the whale is in non-tweet markets.
- **BLOCKED ON SIR:** (1) fund BOT wallet 0xD0f99f...d400 (0 POL / 0 USDC / 0 pUSD) + approvals + pUSD; (2) TwitterAPI.io key; (3) bless bankroll ($1000 env / S2 $300 / Copytrader $150 budgets).
- ⚠️ Alerter risk: manual /sellnow path uses the same CF worker for order POSTs — likely geoblocked now too (untested). Also its PnL Telegram send is failing 400 every minute (separate bug, chip spawned).

## 🏗️ CURRENT: New maker-only bot build spec (2026-07-03)

Full self-contained build spec (hand to a dev): https://docs.google.com/document/d/1TG4tdWR07Ob-vm4MD9dJpomoFwoIR8e5CUka3OvkLfM/edit (Parts A-O). Plain-English: 1yEkXd7xQe3-frnntb_Oh4617kQ5lb_0JRmY41wB9oKo. Diagram + everything else in memory `new_bot_master_build_2026_07_01` and `NEW_BOT_PLAYBOOK.md`.

**Locked decisions:** MAKER-ONLY, post-only limit orders, never takes. Ship first (paper): S2 Basket-Hold + Copytrader. Copytrader = OPTION B (2026-07-03): a MAKER-QUOTING module using a proven MM whale only as a market/bracket SELECTOR, quoting its own two-sided post-only limits (NOT a passive fill-mirror, which is adversely selected). Cut Spike. Gated behind ~July-9 L2 backtest: S4 finish-line, S1, S3, speed/overreaction. S5 sweeper ON HOLD.

**Hosting:** now = Railway EU-West (Amsterdam) + Cloudflare Worker proxy for the geoblock (good enough for sub-second maker). Dublin VPS (AWS eu-west-1) is GATED, only for the microsecond crypto sweep.

**DEFERRED - Rust hot path for the crypto sweep:** if/when we test the 3-second sweep on crypto Up/Down (BTC/ETH), it slots in as a new module but needs (a) its own crypto price feed + resolution clock and (b) the microsecond speed stack: port ONLY the hot-path execution worker to Rust (polymarket_client_sdk_v2 or polyfill-rs) on the Dublin VPS. Python loses a FIFO queue race by 15-40ms. Build only after the July-9 backtest justifies it. Everything else stays Python + maker-only.

**Dashboard:** upgrade the read-only Next.js dashboard to a TradingView-style live terminal (lightweight-charts): per-bracket charts, live book depth with OUR resting orders overlaid, positions + P&L, fills tape, per-module health + start/stop toggles. Behind a login.

**Pre-build gaps closed 2026-07-03:** paper/prod Supabase isolation; on-chain redemption/claim flow + gas reserve; API rate-limit backoff; capital/funding plan; concurrent-auction handling; VPS key security. External-AI QA of the spec triaged in Part K.

## 🎯 SPORTS SWEEP + BACKLOG (2026-07-11)

Sports garbage-time sweep validated (5-day OOS, +2-3% ROI real fills+fees, MLB). Modules live in PAPER: `sports_sweep` (deep-discount maker bids on decided favorites, HOLD to resolution - a price stop-loss BACKFIRES, +$290 hold vs -$6,791 stopped; game-state gate via free MLB StatsAPI to skip high-leverage spots) + `arb_scanner` (complete-set arb detector, paper). Recorder `polybot-mlb-recorder` on Railway EU banking all 4 US sports.

**Backlog (Sir-requested, prioritized):**
1. **Portfolio sizing / cross-strategy Kelly (#4)** — size each strategy's bets by edge/variance with correlation (sweep games correlated within a night; Elon vs sports uncorrelated). Add a portfolio allocator: per-strategy budgets (modules.budget) + fractional Kelly within each + a portfolio-level exposure cap. Design before code.
2. **Position-sizing experiments (#9)** — backtest different buy-in schemes (fixed-$, fixed-%, Kelly, ladder) on the sweep to maximize risk-adjusted return / minimize drawdown. Build a sizing-sweep harness over the phase6 data.
3. **Live game-state for NBA/NHL/NFL** — extend game_state.py to ESPN's feed (StatsAPI is MLB-only) so the sweep's leverage gate works for all sports.
4. **Redundancy / hot-standby** — a second execution box in another allowed region that takes over if Dublin dies (so we never miss a sweep window or get stuck in a position). Watchdog already alerts; add failover.
5. **Maker LP-reward layer** — a market-making posture (tight two-sided quotes NEAR mid on liquid markets) to harvest Polymarket's Liquidity Rewards (paid daily for resting near mid, fill-or-not). Distinct from our current far-from-mid sweeps. New strategy.
6. **BOT wallet collateral access (BLOCKER for live).** Polymarket UI shows $921.74 available on the BOT proxy 0xD0f99f553...d400 (signer EOA 0xbB82715E68cc48Aa0726fA344b930d83fA1618db controls it; SDK classifies POLY_PROXY correctly). BUT the bot's SDK reads $0 collateral AND on-chain shows $0 pUSD/USDC/USDC.e on both proxy + signer. Discrepancy = the deposited balance is not yet spendable on-chain collateral for the bot (likely: one-time exchange APPROVALS not set for pUSD + the V2 CTF/Neg-Risk exchanges, and/or deposit not settled to on-chain pUSD in the proxy). Resolve before live: confirm deposit form + run the one-time approvals from the signer. Definitive test = one $1 post-only from Dublin (rests or errors 'insufficient balance').
7. **Game-state as WIN-PROBABILITY (elite upgrade).** Turn score/inning/outs/bases into p_true via an MLB win-probability table, then trade on edge = p_true - market_price (BUY when price < p_true - margin). Unifies the sweep (cheap ask below true value) AND overreaction-buys (price panics on a scare but the game is still safe). Current game_state.py is a binary decided/danger gate (v1); the win-prob is the elite version.
8. **Fast poll for overreaction-buys.** The sweep (rest bid) needs no speed. But catching a price OVERREACTION to a scare (price 0.80, true still 0.95) is a seconds-window edge -> add a fast poll loop (~5-10s) for LIVE games only. No co-location / microseconds needed (nobody HFT-races baseball).
### ⚡ LATENCY BASELINE (measured on Dublin VPS 2026-07-11)
Dublin (AWS eu-west-1) → Polymarket, reads + signing (no orders placed):
- **CLOB authed round-trip (balance / open-orders): ~26ms p50, ~31-40ms p95.** This is one order-POST leg.
- TCP+TLS cold connect: ~35ms (amortized away by keep-alive).
- Gamma /events read: ~54ms p50, 232ms p95 tail (data path, not hot-path critical).
- **Order SIGNING (create_signed, not posted): ~43ms p50, spikes to ~990ms** when the SDK fetches market metadata/tick over the network.
Interpretation: hot-path fire (cancel + post pre-signed) ≈ **2×26 ≈ ~52ms network**, signing kept OFF the timed path. The ~43ms-to-1s signing jitter VALIDATES the pre-sign design (never sign in-path). Our latency foundation is solid (ref desk showed 344ms; we're ~26ms/leg). Re-run harness: reads/sign timing block (keep in `scripts/`), never place real orders in a benchmark.

### 🧭 DECISIONS (Sir 2026-07-11)
- **TwitterAPI.io / tweet strategies: ON HOLD** — no tweet strategy has survived backtests yet. Do NOT buy the key or build the tweet stream until a tweet edge is proven. Tweet-specific speed lane (warm pool, pre-signed ladder wiring, hot-path activation) is parked with it.
- **BUT build the NON-tweet speed/quality hardening NOW** (applies to the sports sweep + arb + any maker strategy): adverse-selection modeling in backtests, TCP_NODELAY on the CLOB transport, the `feed_guard` price-validation util. These don't need TwitterAPI.
- **Win-prob model: sharpen** (calibrate vs recorded MLB finals). **Dashboard: add live-latency logging + realtime**, and DEPLOY the redesign to Railway `polybot-dashboard`.
- **Backtest session (`polymarket // backtestsrun`): QA DONE 2026-07-11.** Independent audit results:
  - ✅ **TRUST the REJECTED verdicts** — seesaw (sweep_grid walk-forward, bracket-hit ≈61% for every projection model), arb (arb_july6, YES+NO≈1), Elon books -EV (backtest_books) are CLEAN and correctly rejected. Don't re-litigate.
  - ⚠️ **DO NOT TRUST two positive claims:** (1) **MLB sports-sweep "+2.35% CONFIRMED +EV"** is OVERSTATED — it's a per-FILL band ROI (pseudo-replication); honest unit is per-GAME (n≈29, 1 collapse), fat tail (-96%) wider than the edge, 95% CI spans zero, and phase5 (fee=0) vs phase6 (real fee) disagree. → **sports_sweep stays PAPER-ONLY until re-validated per-game on forward OOS data with a bootstrap CI (lower bound must be > 0).** (2) **Tweet-reaction "speed Test B viable / first non-efficient edge"** RETRACTED — top-of-book full-clip fill artifact (depth sim loses on both auctions); the +2.9c is forward-conditioned. Memories [[crypto-sweep-backtest]] + [[tweet-reaction-speed-test]] corrected.
  - KNOWN FIX PENDING: reconcile phase5_mlb_slate fee (=0) with phase6 (real sports taker fee); phase6 is correct.

### 🤖 AUTONOMOUS SESSION 2026-07-11 (Sir away 2h) — shipped
- ✅ **Dashboard redesign LIVE** at **https://polybot.xagency.com** (custom domain; `railway up` from web/). Overview + per-module tabs + Latency. Favicon fixed (was behind the auth gate → 401'd; now icon.svg + favicon.ico serve publicly, verified 200).
- ✅ **Speed hardening** built + deployed to Dublin: `net_tuning.enable_tcp_nodelay()` (Nagle off, all sockets, at boot) + `FeedGuard` util (drop-first/dedup/stale/delta-reject) for the recorder + speed lane.
- ✅ **Backtest QA** (above) + memory corrections.
- ⏳ Still queued: win-prob calibration (needs OOS game-outcome data; deferred to avoid a rushed bad calibration), live-latency logging + realtime dashboard, per-game sweep OOS rerun (phase6 pmxt pulls too slow this session).

### 📋 TWEET-HARDENING → folded into Step 5 (Speed lane) (2026-07-11)
From @0xSurferX's 6-failure-pattern thread. Scorecard: we COVER backtest-realism, win-rate-vs-entry (edge=p_true-price), simplicity, break-even discipline. The 2 partials + extras below are INCLUDED in Step 5 (not built now - the 5-min sweep doesn't stream, so streaming-validation would be speculative until the speed lane exists):
1. **Feed-validation layer** (Part 1): warm connections ~15s before a window opens; run N parallel connections and take the first clean deduped tick; DROP the first (cached) tick per connection (already in `tweet_stream.py`); reject any tick >~15c delta from last-known-good; stagger connection startups across ~1s. Build as `api/modules/shared/feed_guard.py`, consumed by tweet_stream + recorder + speed lane.
2. **TCP_NODELAY + zero-serialization on the hot path** (Part 5): set TCP_NODELAY on WS + the CLOB transport; keep the timed fire section free of JSON build / logging (hot_path.py already clones + sends pre-signed).
3. **Adverse-selection modeling in backtests** (Part 2): model that resting bids fill DISPROPORTIONATELY when the market is about to move against us. The sweep is largely immune (hold-to-resolution + game-state danger-skip), but any quote-and-flip strategy (S1/S3) must price it.
4. **Regime / entry-price testing** (Part 4/6): test the sweep's edge by window-open vs 60s-in, US vs Asian hours, weekday vs weekend; add a time-of-day / weekend filter where the edge concentrates. Pure backtest on recorded L2 + finals; run before scaling.

9. **✅ BUILT (2026-07-11) — trading-desk dashboard redesign.** `web/` now has a tab bar: Overview + one tab per active module + Latency. Overview = P/L hero (lightweight-charts area chart + 1D/1W/1M/1Y/YTD/ALL toggles) + performance stat cards (closed 24h, avg edge, fill rate, breaker trips, CLOB RTT, unrealized) + live Scan Engine signal feed + live orders + status bar. Per-module tabs filter P/L/signals/orders/positions. Reads Supabase only (zero bot-API coupling). Per-panel ErrorBoundary; chart-time dedupe fix. Verified live in paper. **Remaining polish:** live-latency logging into the Latency tab (currently the measured baseline), realtime (Supabase subscription vs 15s poll), deploy to a host (Vercel) behind the password gate. Original spec kept below for reference.
   **⏸️ Original spec (now built):** Restyle `web/` into a single OVERVIEW page + a TAB per module (Overview | Sports Sweep | Basket Hold | Copytrader | Arb Scanner | Latency/Monitor). Target look (Sir's ref screenshot): dark theme, gold+green accents, big all-time P/L with 1D/1W/1M/1Y/YTD/ALL toggles, cumulative P/L area chart, a live streaming engine-log panel ("scan/probe/EDGE" lines), a LIVE ORDERS table (token/side/size/price/scoring), and PERFORMANCE stat cards (pairs/positions closed 24h, avg edge, fill rate, leg-risk events, avg latency, uptime) + a bottom status bar (orders/scoring/inv uPnL/fills/merges/rewards). Adapt METRICS to our maker strategies (not arb-pairs). **ZERO bot-speed impact** by design: dashboard is a separate read-only Next.js app that reads Supabase (bot state), never the Dublin execution box or the signing/hot path. Only rule: dashboard reads Supabase, never polls the bot's own trading API. **HOLD until current issues clear** (real-money $1 confirm + latency benchmark + first strategy micro-live). See [[reminder-dashboard-redesign]].

## 🧭 NEXT STEPS / PARKED (2026-07-02) — cross-market expansion (do AFTER Elon is shipped)

The reconstruction engine (brackets -> implied fair value) is validated and market-agnostic, and Elon is efficient, so the real upside is OTHER markets. Parked, focus is Elon right now:
- **Market SCANNER (build this):** run the reversion-corr screen (`scratchpad/reconstruct_other_markets.py` prototype) weekly across EVERY bracketed Polymarket market -> an auto-ranked watchlist of the least-efficient crowds. Catches baseball / weather / new bracketed markets the moment they list. Highest-leverage infra we can build.
- **Player-prop lead (validate):** the scan flagged soccer PLAYER-PROP markets as mean-reverting (revert_corr +0.22 to +0.28 vs efficient Elon +0.037). MUST validate on real L2 depth (pmxt has these markets) before trusting, the reversion may be thin-book bid-ask bounce that doesn't survive spread. If real, this is a fadeable market.
- **Baseball / weather:** not currently listed as bracket markets (seasonal). The scanner picks them up automatically when live. Same engine, each market recovers its OWN formula (the Elon formula `0.38*count+0.46*naive+25` is Elon-specific).
- **Reconstruction engine** lives in `_DataMetricPulls/pacing_backtest/pace_reconstruction.py` (Elon) and is the transferable asset. See memory `edge_map_elon_efficient`.
- **How to point it at any market:** give the market name / URL / tag / condition ID + a date range; resolve to condition IDs via Gamma; pull L2 from pmxt into `l2_history/`.

## 🤖 BOT MECHANICS: how it works start to finish + where the edge is (saved 2026-06-29)

Companion artifact: the **'Strategy Walkthrough' tab** in the Elon pacing sheet (gid 1854179039) walks one mock 2-day auction scenario-by-scenario for both strategies below.

**The two candidate strategies**
- **S1 Pace-Scalp (active microstructure):** continuously compare each bracket's live PRICE to its model FAIR value; buy too-cheap, sell too-rich, flip on the seesaws. Monetizes the market's repricing MISTAKES (needs the market to converge). Needs automation + speed + liquidity. Many small wins, small frequent losses, dies in thin books.
- **S2 Basket-Hold (range bet):** pick the 2 brackets around the projection, accumulate at dips BELOW fair via limit orders, HOLD to resolution. Monetizes the TRUTH (does NOT need the market to converge). Rare but large losses if the count escapes the band. Human-friendly, robust at today's liquidity.

**The core loop (S1, step by step)**
1. Live X feed + L2 book recorder see a new Elon tweet.
2. Counter updates the in-window count (noon-ET window; originals + quotes + reposts + self-replies).
3. Model re-projects final count + uncertainty band (AccrualCurve embeds sleep; regime detector adjusts the level).
4. Convert projection to a fair probability per bracket.
5. Compare fair vs live price. Bracket cheaper than fair by more than spread+fees, fire a LIMIT buy at/inside best. Richer than fair, sell/skip.
6. On overshoot, sell into the spike and rebuy lower (seesaw). Stop out if the move is momentum, not reversion.
7. Size each bet by fractional Kelly scaled to confidence (narrow band = bigger, wide band = ~0).

**Where the edge actually is (proven 4x):** the POINT forecast is saturated. The market out-forecasts every pacing model (Kalman / Accrual / Particle Filter all land at ~market accuracy at the bracket level). So the edge is NOT a better forecast, it is MICROSTRUCTURE: (a) speed / repricing-lag right after a tweet, (b) overshoot mean-reversion (the seesaw), (c) boundary coin-flips late, (d) structural full-set arb when bracket prices sum under $1. All of these need the L2 tick data the recorder is now capturing. Backtest scheduled ~2026-07-09.

**Dark-zone / regime handling (real vs myth):**
- SLEEP (3-9am ET): already handled. The AccrualCurve advances ~0 in those hours, so the projection does not drift. No manual rule needed.
- BIRTHDAY (Jun 28): NO suppression. Clean X-API: 2024 = 184% of baseline, 2025 = 90%. Do NOT add a birthday multiplier, it would hurt accuracy. ("He's quiet on his birthday" is not supported by data.)
- EVENTS (217 tested): mostly weak. Only validated event signal is the SpaceX launch-repost (~50% of launches, +1 about 87 min after liftoff).
- STRONGEST un-wired signal = EARLY-BURST predicts a heavy day (45 vs 21 avg). This is the regime filter worth wiring next (a LIVE detector, not a calendar of beliefs).
- RULE: only apply an event/regime multiplier the DATA confirms across 2-3 clean instances. The `_Config` modifiers (GOLF / RALLY / etc.) are unvalidated guesses, validate before trusting.

**Posting-rate context (so baselines do not confuse):** his counting-rate GREW over time. June 2024 ~9/day, June 2025 ~23/day, 2026 ~27-30/day (matches the dashboard's 30.7). The Jan 2026 peak hit 68/day. Always state which era a baseline came from.

**vAI's recommended build order:** ship S2 first (sturdy, works at today's liquidity), size off model + band, accumulate only on dips below the band's fair sum. Layer S1 on top only after the recorder L2 backtest proves the speed/seesaw edge survives spread + fees.

---

## 🏎️ NEXT-STEP — World-class Elon-tweet trading bot architecture (saved 2026-06-25)

**Goal:** sub-300ms tweet-to-fill on Elon tweet auctions. Compete with the pro Polymarket bots.

**Current state (2026-06-25):** Tier 1A is shipped — pre-signed orders at arm time, faster polling (2s), CF Worker proxy for geo-bypass. End-to-end ~1.5s. The roadmap below is for when Sir wants to push to world-class.

### Tier 1A — shipped (~1.5s tweet → order)
- ✅ X API polling 2s (was 8s) — was Sir's "I pay per poll" insight
- ✅ Pre-sign order at arm time (stores SignedOrder dict in Supabase)
- ✅ Token_id pre-cached at arm time (no Gamma lookup on fire)
- ✅ CF Worker proxy at `polymarket-proxy.darwin-38f.workers.dev`
- ✅ On fire: ONLY POST the pre-signed order (skip sign step, skip book read)

### Tier 2 — pro-grade target (~400-600ms tweet → order, ~1 day work)
- **X Streaming API** (`POST /2/tweets/search/stream`) with filtered rule `from:elonmusk` — sub-300ms push delivery, replaces polling entirely. Requires X API Pro plan.
- **Pre-sign 5 staggered orders** at arm time: prices at best_ask, +1c, +3c, +5c, +10c. At fire time, pick the right one based on tweet metadata/current ask. Eliminates the "stale pre-sign" risk.
- **WebSocket CLOB book subscription** — `wss://ws-subscriptions-clob.polymarket.com` keeps best_ask in memory continuously. Pre-decide which pre-signed order to submit before fire.
- **Local LLM tweet classifier** — small model (Qwen/Llama 3B) running on the box, classifies tweet sentiment in <50ms. Picks the right pre-signed order without a Gamma round-trip.

### Tier 3 — world-class (~150-300ms tweet → order, ~1 week + infra cost)
- **Bare-metal in Equinix NY4 / NJ datacenter** ($100-200/mo) — single-digit ms RTT to Polymarket's CLOB infra (also in NJ). Railway US East is ~50ms away; co-located drops it to ~5ms.
- **Non-US wallet** — bypass the geo-block at the wallet level (CFTC scope is jurisdiction-based, not IP-based). Singapore/Cayman/Estonia LLC owns the wallet, EOA signs from non-US. Removes proxy hop entirely. Legal review required.
- **X mobile-API tap** — some pro bots watch X's `home_timeline.json` mobile endpoint via authenticated session cookies. Sees tweets ~100ms BEFORE public streaming API delivery because CDN edge replication.
- **Multi-wallet parallel submission** — 3-5 sub-wallets pre-funded with bracket budget. On tweet: submit pre-signed orders in parallel from each → wins racing other reactive bots. Atomic dedup via on-chain conditional execution.
- **Order-book imbalance front-runner** — watch the book for OTHER bots' reactive orders forming. Their orders leak intent ~20ms before fill. Front-run by submitting milliseconds earlier.
- **Pre-signed cancel orders** — if the tweet shifts thesis the wrong way, instantly cancel the pre-signed buy (also pre-signed at arm time).

### Tier 4 — moonshot (sub-100ms, ~1 month + significant infra)
- **Custom mempool monitor on Polygon** — see other bots' transactions before block inclusion. Pre-empt their orders.
- **Private order routing** with Polymarket — talk to Polymarket Pro / institutional desk for priority API access.
- **Multi-region failover** — bare-metal in NY, Singapore, EU; pick fastest path per request.

### Hard constraints
- **Polymarket CFTC block on US IPs**: must use CF Worker proxy OR non-US server. No way around for US-based wallet operation.
- **Polymarket CLOB matching engine throttling**: even with sub-100ms detection, the matching engine processes orders FIFO with some latency. Floor is likely ~50-100ms even with co-location.
- **X API tier limits**: Streaming requires Pro plan (~$5k/mo) or Enterprise. Polling is Basic-tier OK but caps detection floor at ~250-500ms.

### vAI's recommended priority order
1. **Tier 1A** (shipped) — get it working, validate the loop end-to-end
2. **Tier 2 WebSocket book** — biggest single latency win (~500ms saved)
3. **Tier 2 Streaming X** — only if Sir wants to scale beyond reactive (and is OK with Pro plan cost)
4. **Tier 3 co-located server** — only if Sir is competing with other top bots and wants to win race conditions

---

## 🛑 PRIOR STATE (2026-06-16) — BOT TORN DOWN FOR FRESH REBUILD

The bot is **NOT live**. Everything below this banner describes the PRIOR running system and is kept for rebuild reference only — do not assume any of it is currently deployed.

**Removed**
- Railway project `Polymarket-Bot` (`e9d87bab-d38a-42e3-b57a-f197c4b081cb`): all 4 services deleted (Bot-API, Bot-Dashboard, cron-spike-alert, cron-anchor-alert). Empty project shell kept. In-process schedulers gone.
- Supabase `xdonwowgqvmtrduikaon`: all public tables TRUNCATEd (0 rows, verified). Schema + 23 migrations + keys intact.

**Kept (do NOT delete)**
- All credentials in `~/.credentials/shared.env` (`POLYMARKET_*` + `SUPABASE_*` blocks; wallet key verified). `LUNARCRUSH_API_KEY` + `WEBHOOK_SECRET` appended during teardown.
- Supabase project (reused — deleting = new keys), GitHub repo `udt1234/polymarket-trading-bot-3.21.26`.

**To rebuild**: deploy a fresh Railway service, reconnect the GitHub repo, re-paste env vars from shared.env, point at the same Supabase URL. Optionally downgrade Supabase to free tier to pause billing during the gap.

---

## 🎯 Next Session — Configure Exit Rules (Elon + Truth Social)

**Status (2026-05-21)**: Both ensemble modules currently have NO exit logic.
Live config has `stop_loss_pct = 0`, no `take_profit_pct`, no
`trailing_stop_pct`. Bot enters positions and HOLDS TO AUCTION RESOLUTION.

**Implications**:
- Bracket wins → position pays $1 → realized P&L = (size × $1) − cost
- Bracket loses → position settles at $0 → realized P&L = −cost (full loss)
- Bot does NOT exit early on adverse price moves
- Bot does NOT lock in gains when price runs up

**Sir to decide**:
1. Add stop-loss? (e.g. exit if price drops -30% from entry)
2. Add take-profit? (e.g. exit if price runs +50% from entry)
3. Add trailing stop? (e.g. lock in 25% retracement of peak gain)
4. Or keep hold-to-resolution as the thesis?

**Spike Trading reference** — already has active exit logic: stop_loss,
take_profit, trailing_stop, sellnow_grid, pacing-based classifier.
Could port that pattern to Elon + Truth Social if Sir wants active exits.

**Files to touch when implementing**:
- `api/modules/elon_tweets/module_config.py` — add exit-rule defaults
- `api/modules/truth_social/module_config.py` — same
- `api/services/exit_manager.py` — already wired to module_config exit
  fields; just need values set

---

## 🔮 Backlog (parked, prioritized later)

### Gnosis-Safe Deployer Watcher — front-running new market listings (deferred 2026-05-18)
**Status**: Researched + scoped. NOT building yet — current modules' fill problems must clear first.

**Edge thesis** (validated via outside research):
Polymarket deploys new auction markets from a deterministic gnosis-safe wallet
on Polygon. Other bots wait for the Polymarket REST API to surface new
markets, which lags the on-chain deploy by 5-30 min. A bot watching the
deployer wallet directly on Polygon catches a new listing 5-15 min before
the REST-polling bots, hitting the order book while it is still thin.

**Build plan when prioritized**:
1. Identify the deployer wallet (Polygonscan trace on 5-10 recent Polymarket
   market contracts; confirm a single deterministic source address).
2. Subscribe to Polygon `newPendingTransactions` via Alchemy free tier
   (300M compute units / mo, plenty for one-address filter).
3. Decode calldata on detection -> extract new conditionId / market slug.
4. Bridge to existing `engine.insta_buy()` ladder once Polymarket CLOB API
   exposes the new market (poll for ~30-120s after on-chain confirmation).

**Effort**: ~1 day of focused work.

**Why deferred**: insta-buying new auctions is solving the wrong problem
when the bot is rejecting ~1000+ signals/day on auctions that ARE already
listed. Fix existing-market fill quality first (PRs #71-75 + this PR),
then revisit.

---

## 2026-05-18 — Module fill quality + observability sprint (PRs #68-76)

**Outcome**: Truth Social trading actively (12+ fills/24h). Elon + Copy Trading cycling cleanly with new gates. Dashboard now surfaces "is this module ACTUALLY working" separately from operator-intent status. Daily QA agent scheduled (free, runs under subscription).

### Shipped
- **PR #68** copy_trading — shadow_mode default → False, heartbeat log, strategy string aligned
- **PR #69** elon_tweets — pre-emit MIN_PRICE_FLOOR + empty-book diagnostic
- **PR #70** truth_social — tick-snap at emit + pre-emit floor filter
- **PR #71** spike — CLOB ApiCreds dataclass fix (was crashing 100% of cycles)
- **PR #72** spike — health hook moved out of per-row loop (later removed in PR #76, methods never existed)
- **PR #73** spike — removed 24h `buy_cancel_after_hours` cutoff on Cheap_Lottery_Pacing (lottery = hold to resolution, no cutoff needed)
- **PR #74** dashboard — `realtime_health` field + HealthBadge component (Trading/Cycling/Stuck)
- **PR #75** risk_manager — thin-book BUY bypass for cheap-lottery (<10¢) signals + Elon QUIET regime damp disabled + min_edge_threshold lowered 0.02→0.01
- **PR #76** cleanup — orphan `_record_cycle` calls removed + migration 020 added `positions.updated_at` column + auto-bump trigger (was erroring exit_manager every cycle) + Spike Trading dropped active→paper to clear Polymarket regional geoblock

### Live config patches (not just code — applied directly to Supabase)
- Copy Trading: `max_trade_age_sec` 300→900, `max_price_drift_pct` 20→10, `shadow_mode` true→false
- Elon Tweets: `use_regime_modifier` true→false, `min_edge_threshold` 0.02→0.01
- Spike Trading: `status` active→paper (Polymarket 403 geoblock)

### Daily QA agent scheduled
- `polymarket-bot-daily-qa` runs every day at 9 AM ET local
- Cost $0 (runs under Sir's Claude Code subscription, NOT paid API)
- Notify-only-on-failure: outputs `silent_pass` when all 8 checks green
- 8 checks: cycles flowing, no critical errors, Truth Social fills, Copy whale polling, engine cycle freshness, rejection-volume sanity, geoblock watch, migration sanity
- Caveat: only runs while Claude Code is open; if missed, fires on next launch
- Task file: `C:\Users\darwi\.claude\scheduled-tasks\polymarket-bot-daily-qa\SKILL.md`

### Known issues remaining
- Spike Trading + V2 don't write a `Cycle:` heartbeat log — Health Badge shows "Stuck" even when they're cycling. Next session: add a heartbeat log line at end of Spike's `_evaluate_async`.
- APScheduler skipping some Spike cycles ("max running instances reached") — cycle takes >30s. Throughput half what config suggests. Investigate cycle latency.
- Google Trends 429 rate-limited every Truth Social cycle. Cosmetic, falls back. Add caching or accept the noise.

---

## Current State (2026-05-13)
Bot LIVE on Trump + Elon (ensemble) + Spike Trading (multi-auction multi-strategy plugin architecture; paper-trading via global `PAPER_MODE=true`). All on Railway. **Copy Trading module Phase 1 shipped 2026-05-13** — paper/shadow only, no wallets registered yet; user adds via SQL insert into `copy_trade_wallets` to activate. Dashboard + live promotion in Phase 2/3.

## ⭐ Cross-Module Patterns
Documented in code. See: spike_trading/strategies/ (plugin registry), modules.py:get_pacing (pacing blend), pacing-analysis.tsx (Confidence Bands), BaseModule.get_config_schema, realtime_health endpoint. 11 patterns total.

---

## Module Status (as of 2026-05-18)

| Module | Strategy | Status | Notes |
|---|---|---|---|
| **Truth Social Posts** | ensemble | paper | 🟢 Trading — 12+ fills/24h |
| **Elon Tweets** | ensemble | paper | 🟡 Cycling — QUIET regime + lowered edge threshold |
| **Spike Trading** | pluggable plugins | paper | Dropped from active 2026-05-18 (Polymarket geoblock) |
| **Spike Trading V2** | pluggable plugins | paper | Shares Python class with V1 |
| **Copy Trading** | copy_trading | paper | 🟡 Cycling, polling Pestle wallet |

Spike plugin inventory: `Cheap_Lottery_Pacing` (5-tier `<40`), `Mid_Range_Spike` (6h delayed, arc 65-89/90-114/40-64), `Big_Hold_Monthly` (1400+).

---

## Open Work

### 🚦 LIVE-FLIP PROCEDURE (Spike Trading)
1. **Polymarket geoblocks Railway US IP** (confirmed 2026-05-18 via 403 errors). Need VPN/region change BEFORE flipping live.
2. Run `python scripts/backfill_position_token_ids.py --apply` (lives SELLs need `positions.token_id`).
3. Apply migration 015 (`positions_token_id.sql`).
4. Railway env: `PAPER_MODE=false`, `ENV=production`; `SLACK_WEBHOOK_URL` set.
5. Dashboard → Spike module → status → "Real $ Trades" (writes `status='active'`).
6. Watch next cycle log for `"Live executor ready"`.

### Whale Watching card (Phase 2 of `WHALE_BRACKET_CARDS_SPEC.md`)
Zero files exist yet. Needs: `whale_snapshots` + `whale_wallet_profiles` Supabase tables, `whale_classifier.py` (5-archetype detection: Market-Maker / Tail Scooper / Spike Trader (=us) / Pace Chaser / Tail Punter), `whale_snapshot.py` orchestrator, nightly Railway cron, `/api/modules/{id}/whales` endpoint, 5 TSX components. Recommend: Spike-only first + 90-day backfill (~half a day). Spec estimate: 8-10 hr full Phase 2.

### Other priority work
- Configure exit rules (top of file) — Elon + Truth Social have none
- Bot-vs-market disagreement gating (warn when bot top diverges >30pp from PM top)
- Bracket arc analysis for monthly auctions (need more samples)
- Cache `_first_enabled_auction()` in spike module (QA-flagged perf)
- Auth on `/modules/*` router (pre-existing security gap)

---

## Key Config

| | Value |
|---|---|
| Trump module ID | `e858d9ed-da0d-4e9a-8bef-2c2830686a5a` (Truth Social Posts) |
| Elon module ID | `cac300cb-5af2-4c25-a7df-3069478aefdb` (Elon Tweets) |
| Spike module ID | `4faba37c-906b-405f-ad49-737b12e75b16` (Spike Trading) |
| Slippage tolerance | 0.05 |
| Auto-pause threshold | 5 consecutive losses |
| Order TTL | 5min default; 24h for Spike BUYs |
| Dashboard widths | full / 1/2 / 1/3 (CSS grid) |
| Daily Slack digests | 9 AM ET + 5 PM ET (UTC 13:00 + 21:00) |

## URLs
- Dashboard: polybot-dashboard.up.railway.app
- API: polymarket-trading-bot-32126-production.up.railway.app
- Prod Supabase: xdonwowgqvmtrduikaon.supabase.co

## Operational
- Trump backfill: ✅ complete (32,880 posts, walked to 2022). `backfill_progress.is_complete=true`.
- IFTTT webhook for Elon X: needs `WEBHOOK_SECRET` env var; payload spec in `api/routers/webhooks.py`.
- Backfill scripts: `scripts/backfill_xtracker_history.py` (idempotent, ~5min) + `scripts/backfill_truth_social.py` (idempotent, 8-24h, `--forward` for incremental).
- Parquet historical: streamed via `_DataMetricPulls/duckdb_remote.py` — HF token in `~/.credentials/shared.env`.
- Pre-2026-05-05 session history preserved in git (`git log --before=2026-05-05`).
