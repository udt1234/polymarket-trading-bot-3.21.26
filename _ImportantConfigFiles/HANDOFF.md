# PolyMarket Bot — Handoff

## Current State (2026-05-04)
Spike Rider module shipped (paper-only). Trump + Elon modules still LIVE & TRADING. Sell-rule simulator validated `multi_stage_2x_3x_5x` as the winning exit on 211 historical Elon brackets (78% win rate, +155% median return).

## Spike Rider Module (NEW — 2026-05-04)
- New module `api/modules/spike_rider/` — buys cheap brackets early, rides spikes, exits per configurable sell rule
- New tables: `auction_series` (handle/title_filter mapping), `position_exit_state` (multi-stage tranche tracking)
- Migration: `supabase/migrations/010_spike_rider.sql` — **APPLY MANUALLY via Supabase SQL Editor before activation**
- Default config: $10 per entry, entry price band [0.02, 0.40], multi_stage exits at 2x/3x/5x with 30% trailing-stop backup
- Seeded "Spike Rider — Elon" module in `paper` status with `$100` bankroll
- Settings UI: dedicated `SpikeRiderSettings` card on the module page (page.tsx detects `strategy === 'spike_rider'`)
- Sell-rule simulator: `python scripts/simulate_sell_rules.py --module elon` — replays `price_snapshots`, outputs markdown report to `_ImportantConfigFiles/spike_rider_simulator_report.md`
- After migration applied: flip module status to `active` to start paper-trading

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
