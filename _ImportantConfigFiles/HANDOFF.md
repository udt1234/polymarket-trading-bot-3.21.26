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

## Key Config
- Trump: e858d9ed-da0d-4e9a-8bef-2c2830686a5a (entry_gate=0)
- Elon: cac300cb-5af2-4c25-a7df-3069478aefdb (entry_gate=0)
- Slippage: 0.05 | Auto-kill: 5 losses | Order TTL: 5min
- Dashboard widths: full / 1/2 / 1/3 (CSS grid)

## URLs
- Dashboard: polybot-dashboard.up.railway.app
- API: polymarket-trading-bot-32126-production.up.railway.app
- Prod Supabase: xdonwowgqvmtrduikaon.supabase.co
