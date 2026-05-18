# PolyMarket Bot — Handoff

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

## ⭐ Cross-Module Patterns (proven on Spike — apply to all)

Documented in code now; one-liners here for the index.

1. **Pluggable Strategy Plugins** — `api/modules/spike_trading/strategies/` registry. Drop file = new strategy.
2. **Multi-Auction × Multi-Profile Config** — `auction_types[].bracket_profiles[]` with per-profile strategy + params.
3. **Pacing Prior** — recent + DOW + window-filtered historical, blended (`api/routers/modules.py:get_pacing`).
4. **Polymarket-Native Bracket Discovery** — pull from Gamma, never hardcode grid.
5. **Window-Length Filter on Historical Means** — `target_window_days` filter on past trackings.
6. **Confidence Bands UI** — bot prob vs Polymarket price side-by-side (`web/.../pacing-analysis.tsx`).
7. **Schema-Driven Editable Config** — `BaseModule.get_config_schema()` + `<DynamicConfigForm>`.
8. **Status Model** — active / paper / inactive with structured `inactive_reason`. Per-module executor routing.
9. **Closed-Auction Override** — `is_complete=True` snaps projection to actual outcome.
10. **Verified-Parquet Ground Truth** — per-event grouping for winrate, not per-bracket aggregate.
11. **Realtime Health Badge** (2026-05-18) — runtime "actually working" state separate from operator-intent status. `/api/modules/{id}/realtime-health`.

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

### Other high priority
- **Apply patterns 3 + 6 to Trump + Elon ensemble modules.** Their pacing prior is stale and their Confidence Bands don't show Polymarket prices. ETA: ~1 day.
- **Bot vs market disagreement gating.** When the bot's top bracket diverges sharply (>30pp) from Polymarket's top, log a warning and reduce signal confidence. Right now we trust the model unconditionally.

### Medium priority
- **Migrate Trump + Elon to multi-auction config**. Currently single-bracket. Could enable Trump-7day-multi-bracket trading with the same architecture.
- **Bracket arc analysis for monthly auctions** — only 6 monthly samples in cache, need more before relying on monthly priors.

### Low priority
- Cache `_first_enabled_auction()` in spike module (QA-flagged perf).
- ThreadPoolExecutor + asyncio refactor (pre-existing structural risk).
- Auth on `/modules/*` router (pre-existing security gap).

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
