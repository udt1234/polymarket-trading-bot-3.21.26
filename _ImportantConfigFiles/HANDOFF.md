# PolyMarket Bot — Handoff

## 🚧 BUILD PROGRESS (PART J of BUILD_SPEC.md)
- **Step 1 Skeleton: DONE 2026-07-06** on branch `feat/newbot-step1-skeleton`. Fresh `api/` (main, config, health router, BaseModule, auto-discovery registry, demo module); old bot code removed from the branch (kept: `api/modules/shared/`, `api/services/polymarket_proxy.py`; all old code lives on master). Acceptance passed: boot clean, registry discovers `demo`, GET /api/healthz = 200 unauth.
- Supabase schema: all PART H1 tables already exist on `xdonwowgqvmtrduikaon` via migrations 001-021 (schema kept at teardown). No new migration needed for Step 1; Step 2+ adds deltas forward-only.
- Pending Sir: starting bankroll + gas reserve (Step 4 sizing); paper-Supabase isolation choice (Part N).
- **Next: Step 2 Execution core** (CLOB V2 signer, post-only placement, heartbeat daemon, fill poller).

## 🏗️ CURRENT: New maker-only bot build spec (2026-07-03)

Full self-contained build spec (hand to a dev): https://docs.google.com/document/d/1TG4tdWR07Ob-vm4MD9dJpomoFwoIR8e5CUka3OvkLfM/edit (Parts A-O). Plain-English: 1yEkXd7xQe3-frnntb_Oh4617kQ5lb_0JRmY41wB9oKo. Diagram + everything else in memory `new_bot_master_build_2026_07_01` and `NEW_BOT_PLAYBOOK.md`.

**Locked decisions:** MAKER-ONLY, post-only limit orders, never takes. Ship first (paper): S2 Basket-Hold + Copytrader. Copytrader = OPTION B (2026-07-03): a MAKER-QUOTING module using a proven MM whale only as a market/bracket SELECTOR, quoting its own two-sided post-only limits (NOT a passive fill-mirror, which is adversely selected). Cut Spike. Gated behind ~July-9 L2 backtest: S4 finish-line, S1, S3, speed/overreaction. S5 sweeper ON HOLD.

**Hosting:** now = Railway EU-West (Amsterdam) + Cloudflare Worker proxy for the geoblock (good enough for sub-second maker). Dublin VPS (AWS eu-west-1) is GATED, only for the microsecond crypto sweep.

**DEFERRED - Rust hot path for the crypto sweep:** if/when we test the 3-second sweep on crypto Up/Down (BTC/ETH), it slots in as a new module but needs (a) its own crypto price feed + resolution clock and (b) the microsecond speed stack: port ONLY the hot-path execution worker to Rust (polymarket_client_sdk_v2 or polyfill-rs) on the Dublin VPS. Python loses a FIFO queue race by 15-40ms. Build only after the July-9 backtest justifies it. Everything else stays Python + maker-only.

**Dashboard:** upgrade the read-only Next.js dashboard to a TradingView-style live terminal (lightweight-charts): per-bracket charts, live book depth with OUR resting orders overlaid, positions + P&L, fills tape, per-module health + start/stop toggles. Behind a login.

**Pre-build gaps closed 2026-07-03:** paper/prod Supabase isolation; on-chain redemption/claim flow + gas reserve; API rate-limit backoff; capital/funding plan; concurrent-auction handling; VPS key security. External-AI QA of the spec triaged in Part K.

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
