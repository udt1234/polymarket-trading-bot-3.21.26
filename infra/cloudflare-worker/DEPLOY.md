# Cloudflare Worker — Truth Social Proxy Deploy Guide

**Why:** Railway's IP is blocked by Cloudflare from reaching `truthsocial.com`. This Worker runs on Cloudflare's edge network, which Cloudflare doesn't block, and forwards requests transparently. Free tier gives 100,000 requests/day — bot uses ~288/day.

**Time:** ~5 minutes once.

## Part 1 — Set up the Worker (one time)

1. Go to https://dash.cloudflare.com — sign in (free if you don't have an account)
2. Left sidebar → **Workers & Pages**
3. Click **Create application** → **Create Worker**
4. Give it a name like `truthsocial-proxy` (this becomes the URL: `truthsocial-proxy.<your-subdomain>.workers.dev`)
5. Click **Deploy** (it deploys a placeholder, that's fine)
6. Click **Edit code**
7. Delete all the placeholder code in the editor
8. Copy the entire contents of `infra/cloudflare-worker/truthsocial-proxy.js` and paste it in
9. Click **Deploy**

## Part 2 — Configure the auth secret

The Worker checks an `x-proxy-key` header so randoms can't burn your free tier.

1. From the Worker page, click **Settings** → **Variables**
2. Scroll to **Environment Variables** → click **Add variable**
3. Name: `PROXY_KEY`
4. Value: any random string at least 32 chars long. Generate one with:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Save this value somewhere (1Password, etc) — you'll paste it into Railway too.
5. Check **Encrypt** — keeps it hidden in the dashboard
6. Click **Save and deploy**

## Part 3 — Configure Railway

The bot needs two env vars to know about and authenticate to the Worker.

1. Open https://railway.app → **Polymarket-Bot** project → **Bot-API** service → **Variables** tab
2. Add two variables:
   - `TS_PROXY_URL` = `https://truthsocial-proxy.<your-subdomain>.workers.dev`
     (no trailing slash — this is the Worker URL from Part 1 step 4)
   - `TS_PROXY_KEY` = `<the random string from Part 2 step 4>`
3. Railway redeploys automatically when you save

## Part 4 — Verify

After Railway redeploys (~2-3 min):

1. Open the dashboard → Truth Social module page
2. Look at the **Truth Social (Direct)** card
3. Within 5 minutes the next snapshot job runs. Status should flip from
   `unavailable` (red) → `live` (green) with a real post count

If it stays `unavailable`:
- Check Railway logs for `TS_PROXY_URL` mentions
- Hit `https://<your-worker-url>/api/v1/accounts/lookup?acct=realDonaldTrump`
  with header `x-proxy-key: <your key>` from your local machine. Should return
  `{"id":"107780257626128497", ...}`. If not, the Worker code or PROXY_KEY is wrong.

## Troubleshooting

**401 from Worker:** `TS_PROXY_KEY` on Railway doesn't match `PROXY_KEY` on Cloudflare. Re-check both.

**403 from Worker:** Path didn't start with `/api/v1/`. The Worker only proxies that prefix.

**5xx from Worker:** Cloudflare can't reach truthsocial.com (extremely rare, ~5 min/year of downtime).

**Free tier exhaustion:** 100,000/day. Bot uses ~288/day. If you hit the limit it means another caller is using your Worker URL — rotate the `PROXY_KEY`.

## Cost

$0/month forever within free tier. If you somehow exceed 100k/day, the Workers Paid plan is $5/month for 10M requests/day.
