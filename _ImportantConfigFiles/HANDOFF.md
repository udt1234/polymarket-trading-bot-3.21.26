# PolyMarket Bot — Handoff

## 🚨 NEXT SESSION — Codex Audit Fixes Pending Merge (2026-05-23)

Codex CLI ran a parallel audit on `codex/audit-fixes` branch at `C:\Users\darwi\.codex\worktrees\b57c\PolyMarket_Bot`. **Working tree only — never committed.** Live REST cleanup didn't hold because the code fixes were never deployed.

**Reality check (vAI confirmed 2026-05-23):**
- 5 duplicate-waiting pending-signal groups still in DB (worst = 4 dupes)
- 4 zero-share active Spike tracker rows still in DB
- Master HEAD is `228ea14` (retention PR); no Codex commits anywhere

**Fixes that need to land** (12 modified files + 2 new migrations):
- `api/services/engine.py` — pending-signal dedupe + wait_until cap at auction close - 2h + unfilled-on-unlock handling
- `api/services/position_manager.py` — Spike position sync on real BUY/SELL fills (was creating zero-share rows pre-fill)
- `api/services/executor.py` — passes signal.metadata to position open; writes rejection_reason to orders.metadata
- `api/modules/spike_trading/module.py` — removed `_open_position()` pre-fill tracker creation; added `_get_open_or_pending_count()` based on canonical positions + active orders; `_get_open_position()` auto-liquidates zero-share rows
- `api/modules/spike_trading/strategies/{mid_range_spike.py, big_hold_monthly.py}` — added `total_commitment_usd`; convert `pct` → `notional_usd`
- `api/modules/{elon_tweets, truth_social}/module.py` — added `tracking_start`/`tracking_end` to signal metadata
- `api/modules/shared/polymarket.py` — removed duplicate `fetch_all_active_trackings`; added bracket-resolved skip in `fetch_market_prices`; added proxy-usage NOTE comment
- `api/modules/shared/signals.py` — **⚠️ STRATEGY CHANGE**: Kelly BUY gate lowered 0.01 → 0.001 (claim: high-bracket-count auctions split probability finely; portfolio + per-market caps still bound risk). NOT mentioned in Codex export.
- `supabase/migrations/022_pending_signals_dedupe.sql` — cancel duplicate waiting + unique partial index `idx_pending_one_waiting_signal`
- `supabase/migrations/023_spike_zero_share_cleanup.sql` — liquidate zero-share active Spike rows

**Why this matters**: bot can't enter new auctions cleanly until these land. Spike rejects every emit because zero-share rows look open; Elon/Truth keep generating duplicate pending signals that pile up.

**Migration 022 special-case**: Supabase REST cannot run DDL. Must use Supabase SQL editor (vAI did this for retention VACUUM via Chrome MCP), OR Supabase CLI when wired up, OR put SQL into a one-time bootstrap function.

**Outstanding from Codex export (also vAI's responsibility):**
- Credential mismatch: local `SUPABASE_URL=xdonwowgqvmtrduikaon` but `DATABASE_URL`/`DIRECT_URL` point to stale `naaiqwghilbrruuvdoea` project
- Rotate Postgres password printed to Codex terminal (only if Sir shares transcript)

---

## 🎯 Configure Exit Rules (Elon + Truth Social) — older but still open

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
