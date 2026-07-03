# Polymarket Proxy — Deploy Guide

**Why:** Polymarket geoblocks Railway's US IP from real-money order placement (CFTC compliance). This Cloudflare Worker forwards bot traffic through a CF edge IP, which Polymarket accepts.

**Scope:** One Worker covers ALL Polymarket hosts (CLOB, Gamma, xTracker) for ALL bot modules. Set up once. Every module benefits automatically.

**Time:** ~10 minutes once.

**Cost:** $0/mo (free tier = 100k req/day; bot uses ~5k/day).

---

## Part 1 — Deploy the Worker

1. Go to https://dash.cloudflare.com — sign in (free if no account; same login as the Truth Social proxy)
2. Left sidebar → **Workers & Pages** → **Create application** → **Create Worker**
3. Name: `polymarket-proxy` (URL becomes `polymarket-proxy.<your-subdomain>.workers.dev`)
4. Click **Deploy** (placeholder code is fine for now)
5. Click **Edit code**
6. **Delete all** the placeholder code
7. Open `infra/cloudflare-worker/polymarket-proxy.js` in this repo, copy everything, paste into the editor
8. Click **Deploy** (top right)

## Part 2 — Set the auth secret

The Worker rejects requests without a matching `x-proxy-key` header — keeps randoms off your free tier.

1. From the Worker's page → **Settings** → **Variables**
2. Under **Environment Variables** → **Add variable**
3. Name: `PROXY_KEY`
4. Value: generate a strong random string:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
5. **Check "Encrypt"** so it's hidden in the dashboard
6. Click **Save and deploy**
7. Copy the value — you'll paste it into Railway next

## Part 3 — Set Railway env vars

The bot needs to know the Worker URL + the auth key.

1. Open https://railway.app → **Polymarket-Bot** project → **Bot-API** service → **Variables** tab
2. Add:
   - `POLYMARKET_PROXY_URL` = `https://polymarket-proxy.<your-subdomain>.workers.dev` (no trailing slash)
   - `POLYMARKET_PROXY_KEY` = (the value from Part 2)
3. Save — Railway redeploys automatically (~2-3 min)

## Part 4 — Verify the bot is using the proxy

After Railway redeploys:

1. Hit the bot's API status endpoint (or check Railway logs) for the line:
   ```
   Polymarket proxy ENABLED (httpx patched=True)
   ```
   If it says `DISABLED`, the env vars didn't load.

2. Direct sanity test from your local machine — confirms the Worker itself works:
   ```bash
   curl -H "x-proxy-key: <YOUR_KEY>" \
     "https://polymarket-proxy.<your-subdomain>.workers.dev/gamma/markets?_q=trump&_limit=1"
   ```
   Should return JSON market data. If 401: key mismatch. If 404: path wrong (must start with `/clob/`, `/gamma/`, or `/xtracker/`).

3. End-to-end test: run `/qa-real-trade` against a Spike module flipped to `status=active`. Watch for an actual order fill on Polymarket. THAT is the real proof — not just the env-var check.

---

## How it works (architecture)

```
┌─────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  Railway (US)   │   401   │  polymarket.com  │   ✅    │ Cloudflare Worker│
│  Bot httpx call ├────X───▶│  (geoblocks US)  │◀────────│  (CF edge IP)    │
└────────┬────────┘         └──────────────────┘         └────────▲─────────┘
         │                                                         │
         │  rewrite + x-proxy-key header                            │ /clob/* /gamma/* /xtracker/*
         └──────────────────────────────────────────────────────────┘
```

**Bot side** (`api/services/polymarket_proxy.py`):
- `install_httpx_proxy_patch()` runs once at boot (called from `api/main.py`)
- Monkey-patches `httpx.Client.send` + `httpx.AsyncClient.send` globally
- Every outbound httpx request to a Polymarket host gets URL-rewritten to the Worker + the `x-proxy-key` header attached
- Non-Polymarket hosts pass through unchanged
- When `POLYMARKET_PROXY_URL` env is unset, the patch is a no-op (paper mode / local dev safe)

**Worker side** (`polymarket-proxy.js`):
- Receives requests at `/{clob|gamma|xtracker}/*`
- Validates `x-proxy-key`
- Forwards to the right Polymarket host preserving method, body, and CLOB auth headers
- Returns response verbatim minus cookies

**One env var, all callers covered.** No per-module wiring needed. New modules using httpx → auto-routed.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Boot log says `proxy DISABLED` but env vars are set | Vars set on wrong Railway service or after deploy | Verify on Bot-API service, redeploy |
| 401 from Worker | `POLYMARKET_PROXY_KEY` ≠ Worker `PROXY_KEY` | Re-check both, save, redeploy |
| 404 from Worker | Bot's URL didn't include the prefix | Patch broken — file an issue with the request URL |
| Still 403 from Polymarket | Worker proxied successfully but CF edge IP still blocked | Try Option 2 (Fly.io Toronto proxy) — see HANDOFF.md backlog |
| Slow first response | Worker cold start | Normal; subsequent calls are fast |
| Free tier exhausted | Bot making >100k req/day OR Worker URL leaked | Rotate PROXY_KEY, check for runaway loops |

---

## Cost

- Free tier: 100,000 requests/day — bot uses ~5,000/day
- Paid: $5/mo for 10M requests/day (won't need)

---

## Rolling back

To disable the proxy (e.g. if Polymarket lifts the geoblock or CF edge IPs get blocked):

1. Railway → Variables → delete `POLYMARKET_PROXY_URL` (key var can stay)
2. Redeploy
3. Boot log will say `Polymarket proxy DISABLED` and all calls go direct to polymarket.com

No code change needed.
