# PolyMarket Bot — Handoff

## Current State (2026-04-16)
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
