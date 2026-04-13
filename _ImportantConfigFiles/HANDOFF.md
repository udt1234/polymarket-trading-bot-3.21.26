# PolyMarket Bot — Handoff

## Current State (2026-04-13)
Bot is LIVE and trading (paper mode). 6 open positions on Trump module, $286 invested. Elon module now has dynamic 30-bracket support. Dashboard significantly upgraded with decision logs, bot reasoning, module config UI, and redesigned metric cards.

## What's Done This Session
- **Signal generation unblocked**: Entry gate 0%, time decay floor 30%, Gamma bid/ask (not broken CLOB)
- **Bot is trading**: 6 open positions, 50+ signals generated, spread check now uses real Gamma data
- **Dynamic brackets**: Elon module shows all 30 brackets (was using Trump's 11)
- **Dashboard**: Decision log section with module filter, auto-refresh 15s
- **Module page**: Bot Reasoning blurb, Action History timeline, editable budget, ensemble weight overrides
- **Metric cards redesigned**: Cost Basis, Current Value, Unrealized P&L, Realized P&L, Win Rate, Bankroll %, Edge Found, Spread Health
- **Settings**: Per-module config (entry gate, kelly, stop loss, models, toggles), reset paper trades
- **Layout**: Flex-wrap cards (max 540px), pacing table 2x wide (1104px)
- **Past auctions**: Show "No bets" instead of "--"

## What's Next
1. **Monitor first trades** — bot has 6 open positions, watch P&L
2. **Slippage tolerance** — consider bumping from 0.02 to 0.05 for more trades
3. **Slack notifications** — webhook may be stale
4. **Design polish** — continue layout improvements per user feedback

## Key Config
- Trump: e858d9ed-da0d-4e9a-8bef-2c2830686a5a (entry_gate=0)
- Elon: cac300cb-5af2-4c25-a7df-3069478aefdb (entry_gate=0)
- Spread tolerance: 0.02 (Risk settings)
- Configs: `settings` table, key=`module_config:{id}`

## URLs
- Dashboard: polybot-dashboard.up.railway.app
- API: polymarket-trading-bot-32126-production.up.railway.app
- Prod Supabase: xdonwowgqvmtrduikaon.supabase.co
