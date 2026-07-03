# HANDOFF — Tear down the PolyMarket bot & save credentials

> Paste everything below the line into a NEW session. Best results if that
> session has **Chrome/browser control connected** (so it can drive Railway)
> and the **Supabase MCP** connected. If Chrome isn't connected, the assistant
> can't click Railway — you'll either do the Railway clicks yourself or give it
> a Railway API token.

---

## Task
Help me fully tear down my **PolyMarket trading bot** so I can rebuild from scratch.
I am **keeping all the accounts** (Polymarket, Supabase, LunarCrush, Anthropic, Slack,
HuggingFace, GitHub) and reusing their credentials — only the *bot* goes away.

## Status so far (done in a previous session, 2026-06-15)
- ✅ Supabase project `PolyMarket Bot` (ref `xdonwowgqvmtrduikaon`) — **all 34 tables already TRUNCATED** (schema/project/keys kept). A few heartbeat log rows may have reappeared since.
- ✅ Trading tables archived to JSON + a credentials checklist were saved.
- ✅ Confirmed historically all trades were **paper** (0 live fills; positions all closed).
- ⏳ **NOT done yet:** stopping/deleting the Railway services, and saving the live env-var VALUES out of Railway.

## What still needs to happen
### 1) SAVE CREDENTIALS FIRST (before deleting Railway)
Open Railway → project **PolyMarket Bot** → service **Bot-API (Fast API)** → **Variables** tab, and record the VALUES of these (also check the other services for any):
- `POLYMARKET_API_KEY`, `POLYMARKET_SECRET`, `POLYMARKET_PASSPHRASE`
- 🔴 `POLYMARKET_PRIVATE_KEY`  ← wallet key; losing it = losing wallet funds
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `LUNARCRUSH_API_KEY`, `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `HF_TOKEN`
Store them somewhere private (password manager / local `.env`). **Never commit them to git.**

### 2) DELETE the Railway project (4 components — all go)
- **Bot-API (Fast API)** — the bot engine + in-process schedulers (this is what still writes to Supabase)
- **Bot-Dashboard** — the Next.js dashboard
- **cron-spike-alert** — cron job
- **cron-anchor-alert** — cron job
Easiest: **Project Settings → Danger → Delete Project** (removes all 4 + crons at once).
This also kills the in-process schedulers (daily 03:30 UTC cleanup, Sunday 03:00 UTC archive).

### 3) FINAL Supabase wipe (after Railway is down)
In Supabase project `xdonwowgqvmtrduikaon`, run a TRUNCATE across all public tables to clear
any rows the bot wrote before it was stopped. (Note: the project is on a PAID tier, so it
cannot be "paused" via API without downgrading — truncate is the clean option.)
SQL:
```
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE 'TRUNCATE TABLE public.'||quote_ident(r.tablename)||' RESTART IDENTITY CASCADE';
  END LOOP;
END $$;
```

## Guardrails / do-NOT-touch
- 🚫 Do **NOT** delete or modify the OTHER Supabase project: **`X Agency // Slack Bot`** (`woqxafmrzvhrhnkgmhdv`). Unrelated.
- 🚫 Do **NOT** delete the GitHub repo `udt1234/polymarket-trading-bot-3.21.26` — keeping the code.
- ✅ Keep the Supabase `PolyMarket Bot` project itself (reusing its URL + keys for the rebuild) — wipe data only, don't delete the project.

## Reference IDs
- Supabase org: `dixiyzpyvrlwgtzoveaq`
- Bot Supabase project: `xdonwowgqvmtrduikaon` (us-west-2), URL `https://xdonwowgqvmtrduikaon.supabase.co`
- GitHub repo: `udt1234/polymarket-trading-bot-3.21.26`
- Railway project: "PolyMarket Bot" (services: Bot-API (Fast API), Bot-Dashboard, cron-spike-alert, cron-anchor-alert)
