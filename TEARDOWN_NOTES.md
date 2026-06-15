# PolyMarket Bot — Teardown / Start-Fresh Notes
Generated: 2026-06-15 · Status: PRE-DELETION (nothing destroyed yet)

> ⚠️ This file is for your reference. It does NOT contain real secret values —
> those are not present in this container (only `.env.example` is). The real
> values live in **Railway env vars** and each provider's dashboard. Do NOT
> commit this file with secrets pasted in.

---

## 1. ACCOUNT / SERVICE INVENTORY (what to preserve & reuse)

Pull the actual values from **Railway → your bot service → Variables** before deleting anything.

| # | Account / Service | Credential var(s) | Where the real value lives | Notes |
|---|---|---|---|---|
| 1 | **Polymarket (CLOB API)** | `POLYMARKET_API_KEY`, `POLYMARKET_SECRET`, `POLYMARKET_PASSPHRASE` | Railway env / Polymarket account | API access for orders |
| 2 | **Polymarket WALLET** | `POLYMARKET_PRIVATE_KEY` | Railway env | 🔴 **CRITICAL — wallet private key. Controls on-chain USDC + positions. Lose this = lose the funds.** |
| 3 | **Supabase (PolyMarket Bot)** | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase dashboard → Project `xdonwowgqvmtrduikaon` → Settings → API | Project ref: `xdonwowgqvmtrduikaon`, region us-west-2 |
| 4 | **LunarCrush** | `LUNARCRUSH_API_KEY` | Railway env / LunarCrush account | Social data |
| 5 | **Anthropic** | `ANTHROPIC_API_KEY` | Railway env / console.anthropic.com | News regime classification (Haiku) |
| 6 | **Slack** | `SLACK_WEBHOOK_URL` | Railway env / Slack app | Trade alerts |
| 7 | **HF token** (per CLAUDE.md) | `HF_TOKEN` | `~/.credentials/shared.env` on your machine | Parquet/HF dataset access |

**Other Supabase project in the same org — DO NOT DELETE:**
`X Agency // Slack Bot` (`woqxafmrzvhrhnkgmhdv`, us-east-1) — unrelated to this bot.

---

## 2. 🔴 LIVE-TRADING FINDING (read before deleting)

Queried the bot's Supabase on 2026-06-15:

- **`orders.executor`: 155 LIVE + 283 paper.** Live orders WERE placed.
- **`trades.executor`: 283 paper, 0 live** — no live fills recorded as trades (live orders may not have filled, or fills weren't written here).
- **`positions`: all 18 CLOSED** — no open positions in the main table. ✅
- **`spike_positions`: 477 LIQUIDATED, 4 RESOLVED, but `2 MONITORING + 2 WAITING` = 4 NON-terminal**, last opened **2026-05-24**.
- **Last order/trade: 2026-05-24.** **Logs still flowing to today** → the Railway process is alive but hasn't traded in ~3 weeks.

**What this means:** Tearing down Railway/Supabase does NOT close positions or move money — funds & positions live on-chain under the wallet key. But before wiping, you should:
1. **Save `POLYMARKET_PRIVATE_KEY` from Railway** (item #2 above).
2. **Check the actual Polymarket wallet** (USDC balance + any open positions) using that key / the Polymarket UI, and settle/withdraw as desired. The 4 non-terminal spike positions are most likely long-since resolved auctions the idle bot never updated — but verify against the wallet, don't assume.

---

## 3. DATA ARCHIVE (QA REQUIRED)

> ⚠️ **QA WARNING (per your instruction):** Data correctness is UNVERIFIED.
> Before trusting any of this for the new bot, QA it — especially the
> live/paper split in `orders`, the empty live side of `trades`, and the
> 4 non-terminal `spike_positions`.

Supabase tables & row counts (project `xdonwowgqvmtrduikaon`):
- price_snapshots 138,881 · order_book_snapshots 100,194 · post_count_snapshots 58,898
- logs 37,193 · signals 3,270 · pending_signals 2,147 · elon_tweets 2,103
- spike_positions 485 · spike_state_snapshots 104 · settings 66 · copy_trade_log 65
- trades 283* · orders 438* · daily_pnl 24 · calibration_log 22 · positions 18 · modules 5
  (*authoritative counts from executor query; list_tables estimates differ)

**Archive constraint:** This sandbox CANNOT reach the Supabase DB directly
(Postgres port + REST host are outside the egress allowlist) and parquet
tooling isn't installed, so the full `scripts/archive_supabase_to_parquet.py`
must be run **from your machine / the Railway service** (where DB creds +
network exist):

```bash
python scripts/archive_supabase_to_parquet.py   # dumps all tables → _DataMetricPulls/historical/supabase_archive/
```

---

## 4. TEARDOWN PLAN (recommended scope — nothing run yet)

| Target | Action | Reach from here? |
|---|---|---|
| Supabase `PolyMarket Bot` data | **TRUNCATE all tables** (clean slate) | ✅ via MCP |
| Supabase `PolyMarket Bot` project | **KEEP** (so URL+keys stay valid to reuse) — do NOT delete | ✅ |
| Supabase `X Agency // Slack Bot` | **DO NOT TOUCH** | — |
| GitHub repo | **KEEP** (your code asset; "fresh bot" = clean rebuild, not repo deletion) | flag for your call |
| Local clone | ephemeral container — nothing to preserve | ✅ |
| Railway service + crons | **YOU delete in Railway dashboard** (after saving env vars) | ❌ no Railway access here |
| Scheduled tasks | in-process (03:30 daily cleanup, Sun 03:00 archive) — die with the Railway service | ❌ |
