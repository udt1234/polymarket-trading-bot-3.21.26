# PolyMarket Bot — Handoff

## Current State (2026-05-05)
Bot LIVE on Trump + Elon (paper). Spike Rider v1 (PR #30) was reverted. **Spike Trading v2 (rebuild) shipped 2026-05-05** — see `spike_trading_module_spec.md` and the new `api/modules/spike_trading/` package. Module row inserted in `modules` table with `status='paper'` (id `4faba37c-906b-405f-ad49-737b12e75b16`). Migration `010_spike_positions.sql` applied to prod. Shadow mode default — no live trades until promoted.

### Spike Rider v1 revert checklist (done 2026-05-05)
- ✅ Module row deleted from `modules` table
- ✅ `auction_series` and `position_exit_state` tables dropped
- ✅ All `spike_rider` code reverted via revert commit on master
- ✅ Trump + Elon modules untouched
- See `SPIKE_RIDER_SPEC.md` for the v1 rebuild plan (informed v2 architecture)

## ⭐ NEW: Full 3.5-Year Polymarket History via Parquet (2026-05-05)
We now have free streaming access to the **complete Polymarket trade history** (Nov 2022 → present, 766M trades, 1M markets) via the SII-WANGZJ HuggingFace dataset.

**Tooling added** (in `_DataMetricPulls/`):
- `duckdb_remote.py` — DuckDB connection helper. Streams Parquet files from HF over HTTPS, caches metadata locally, exposes `markets` / `quant` / `trades` SQL views.
- `full_history_analysis.py` — strict-recurring classification + flip-pattern ranking using the full 3.5y dataset.
- `duckdb_cache/polymarket_remote.duckdb` — persistent DuckDB cache (materialized tables live here, ~150MB).
- HF token stored at `~/.credentials/shared.env` as `HF_TOKEN`.

**vs the previous LuciferForge $9 buy** (which we kept):
| Source | Cost | Time | Trades | Markets |
|---|---|---|---|---|
| LuciferForge SQLite | $9 | 30 days (Mar–Apr 2026) | 8M | 9.5K |
| SII-WANGZJ Parquet | $0 | 3.5 years | **766M** | **1M** |

Use `duckdb_remote` whenever you need historical context beyond the bot's own `price_snapshots` table (~3 months) or the LuciferForge sample (30 days).

---

## TODO — Update Trump + Elon Modules with Parquet Data
**Added: 2026-05-05**

We now have access to the **full SII-WANGZJ Polymarket dataset** via DuckDB+HuggingFace streaming (3.5 years of trade history, 766M trade events, 1M markets — see `_DataMetricPulls/duckdb_remote.py` and `_DataMetricPulls/full_history_analysis.py`).

**Goal**: refit/recalibrate the existing Trump and Elon modules using this data instead of the 30-day LuciferForge sample we initially used.

Specific tasks:
1. **Re-run Elon `<40` flip analysis** on full 3.5-year history — confirm or refute the +194% median peak finding from the 19-auction sample.
2. **Recalibrate sell rule thresholds** for Elon module — the Target 2× rule was tuned on 30 days; verify on 3.5 years.
3. **Recompute Trump bracket-level priors** using the full historical price data — feed into ensemble model weights.
4. **Build a "pacing-aware sell rule"** using the full per-trade timestamps (we couldn't do this with 15-min snapshots).
5. **Backfill Trump+Elon `price_snapshots` table** with longer history (currently only Feb-May 2026 for Trump; Mar-May 2026 for Elon) — 3+ years of additional bracket prices available from parquet.

Reference files:
- `_DataMetricPulls/duckdb_remote.py` — DuckDB connection helper with HF token
- `_DataMetricPulls/full_history_analysis.py` — strict-recurring classification + ranking
- `_DataMetricPulls/full_history/STRICT_recurring_full_ranked.csv` — output (when run completes)
- HF token: stored in `~/.credentials/shared.env` as `HF_TOKEN`

---

## Earlier State (2026-05-02 evening)
Bot is LIVE & TRADING. Trump module's 4-day silence resolved (missing pending_signals table). Data Explorer + IFTTT webhook + dynamic-bracket support all shipped today.

## Trump Backfill: ✅ COMPLETE (2026-05-03 00:10 EDT)
- 32,880 total posts in `truth_social_posts` table
- Walked back to Feb 14, 2022 (account creation)
- Backfill ran 179 minutes locally, hit end-of-history (8 consecutive empty pages)
- `backfill_progress.is_complete = true` for `realDonaldTrump`
- CLAUDE.md daily reminder rule downgraded — no more daily nag

## Tonight's Critical Fix (2026-05-02 ~22:10 EDT)
**Trump module had 0 trades for 4 days** — root cause was migration 006 (`pending_signals` table) never applied to prod Supabase. Wait-for-Dip feature was deferring every signal but failing to persist them — silent drop. Fixed by creating the table; 4 deferred entries appeared on the next cycle (2026-05-03 02:09 UTC).
- Migration 006 applied directly via SQL Editor on prod
- Lesson logged in `_ImportantConfigFiles/lessons.md` (2026-05-02 entry)
- `expected_value_bracket` was also imported only inside `_compute_pacing_models` scope, causing NameError in `get_pacing` — moved to module-level import
- Pending signals visible on module page: `Pending Entries (4)` section auto-renders when rows exist

## Where to Watch Pending Trades
- **Dashboard**: Modules → Truth Social Posts → "Pending Entries (N)" card near top
- **Direct API**: `GET /api/modules/{id}/pending-signals?status=waiting`
- **Cancel button**: red X on each row

## Trump Module Status
- Engine running 5-min cycles ✅
- 4 pending entries waiting for price dips (40-59, 120-139, 140-159, 180-199)
- All target prices 45-99% below current → bot expects significant drops
- Auto-refreshes every 30s on dashboard

## What's Done This Session

## What's Done This Session (May 2)
- **Data audit**: verified storage for both modules, identified Elon raw-tweet gap
- **CLAUDE.md daily reminder rule**: nag about Trump backfill until is_complete=true
- **Trump backfill resumed**: was at 29,830 posts, currently ~30,349 walking back to Oct 30, 2022
- **Elon price backfill running**: 109 historical Elon auctions being pulled from CLOB
- **Data Explorer page** (/data-explorer) with full filters: handle, view (raw/counts/prices), date range, hour-of-day, day-of-week, source, bracket. Coverage cards + 3 result table views.
- **IFTTT webhook** for Elon X: POST /api/webhooks/ifttt/{secret}/elon-tweet → elon_tweets table. Public endpoint, secret-authenticated. Migration 009 applied to prod.

## Setup To Do (User Manual)
1. Set `WEBHOOK_SECRET` env var on Railway (random ~32 chars)
2. Create IFTTT applet: Twitter `New tweet by specific user (elonmusk)` → Webhooks POST
3. Body format: see api/routers/webhooks.py docstring
4. Optionally: leave Trump backfill running on Railway as one-shot (currently running on local machine and will stop when Claude Code closes)

## Previous Session State
Bot is LIVE (paper mode). 6 open positions on Trump, $289 invested. Major session: dashboard layout overhaul, paper executor realism, auto-kill switch, Slack notifications wired up, order TTL sweep added.

## What's Done This Session (9 commits)
- **Bracket Cap card**: Editable % of bankroll with derived dollar amount
- **Bankroll → %**: Editable % of account, dollar amount updates live
- **Module P&L chart**: Cumulative P&L area chart with return %, max drawdown
- **Layout standardization**: 3 width tiers (full/half/third) via CSS grid
- **Pacing table**: Full-width, 60/40 split with pacing chart (actual/expected/projected)
- **Paper executor realism**: Price floor (<1¢ rejected), liquidity check, fills at best ask/bid, partial fills
- **Auto-kill switch**: Pauses module after 5 consecutive losses (togglable in Settings)
- **Slippage tolerance**: Bumped 0.02 → 0.05
- **Slack trade notifications**: Wired into engine cycle
- **Order TTL sweep**: Cancels stale submitted/live orders after 5min

## What's Next
1. **Set up Slack webhook** — add SLACK_WEBHOOK_URL env var on Railway (user will do manually)
2. **Monitor fill quality** — check liquidity check rejection rate
3. **Elon module test** — verify pacing chart renders with Elon data
4. **Edge Found** — resurface in analysis section if wanted
5. **Elon X direct fetcher (FUTURE)** — mirror the Truth Social direct fetcher for X/Twitter. Truth Social is Mastodon-based and unauthenticated, so it was easy. X requires a Twitter API v2 bearer token (paid tier for user timelines) OR a session-based scrape via Playwright. Decision pending: pay for X API ($100/mo Basic) vs build a scraper. File location when built: `api/modules/elon_tweets/x_direct.py`. CLI mirror: `scripts/verify_x_count.py`. Wire into `api/routers/modules.py` with the same `truth_social_direct` pattern (rename key to `x_direct`).
6. **Dashboard redesign (next session)** — full module page layout overhaul. Backend post-count tracking is committed but two files are intentionally uncommitted to start fresh: `web/app/modules/[id]/page.tsx` (XTRACKER/TRUTH SOCIAL split in Current Auction card) and `web/app/modules/[id]/components/post-count-divergence-chart.tsx`. Use them as reference or discard.

## Backfill Operations (added 2026-04-24)

### Run migrations
Apply `007_post_count_snapshots.sql` and `008_truth_social_posts.sql` on prod Supabase.

### xTracker full backfill (~5 min, run anytime)
```bash
SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
  python scripts/backfill_xtracker_history.py --handle realDonaldTrump
SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
  python scripts/backfill_xtracker_history.py --handle elonmusk
```
No rate limit; idempotent. Pulls all 26 Trump auctions + Elon's history.

### Truth Social full backfill (8-24 hr, leave running)
```bash
SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
  python scripts/backfill_truth_social.py --handle realDonaldTrump
```
- Idempotent: resumes from oldest stored post on rerun
- Aggressive backoff (up to 15 min) on 403/429
- Walks back to 2022 (account creation), ~33k posts total
- Optional: set `TS_PROXY=http://user:pass@host:port` for residential proxy
- Run with `--max-minutes 60` for time-boxed Railway cron jobs
- Run with `--forward` for incremental (post-backfill) updates

### Railway one-shot deploy for unattended Truth Social backfill
1. SSH/connect to Railway service
2. Set env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, optionally TS_PROXY
3. Run: `python scripts/backfill_truth_social.py --handle realDonaldTrump`
4. Monitor `backfill_progress` table in Supabase dashboard for live progress
5. When `is_complete = true`, switch to `--forward` mode in a daily cron

## Key Config
- Trump: e858d9ed-da0d-4e9a-8bef-2c2830686a5a (entry_gate=0)
- Elon: cac300cb-5af2-4c25-a7df-3069478aefdb (entry_gate=0)
- Slippage: 0.05 | Auto-kill: 5 losses | Order TTL: 5min
- Dashboard widths: full / 1/2 / 1/3 (CSS grid)

## URLs
- Dashboard: polybot-dashboard.up.railway.app
- API: polymarket-trading-bot-32126-production.up.railway.app
- Prod Supabase: xdonwowgqvmtrduikaon.supabase.co
