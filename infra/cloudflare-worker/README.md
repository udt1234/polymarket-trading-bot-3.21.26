# Cloudflare Worker — Truth Social Proxy

Free Worker that proxies `truthsocial.com/api/v1/*` requests so the bot can
keep cross-checking Truth Social post counts even though Railway's IP is
Cloudflare-blocked from reaching truthsocial.com directly.

## Files

- `truthsocial-proxy.js` — the Worker source. Paste into Cloudflare dashboard.
- `DEPLOY.md` — step-by-step setup guide. ~5 min once.

## Bot integration

`api/modules/truth_social/truthsocial_direct.py` reads two env vars:

| Env var | Where set | Purpose |
|---|---|---|
| `TS_PROXY_URL` | Railway | Base URL of the Worker, e.g. `https://truthsocial-proxy.you.workers.dev` |
| `TS_PROXY_KEY` | Railway | Auth key matching the Worker's `PROXY_KEY` env var |

When `TS_PROXY_URL` is set, all requests route through the Worker. Otherwise
the bot tries the direct truthsocial.com endpoint (which currently fails due
to the Cloudflare block).

## Why a Worker not a residential proxy?

- **Residential proxy:** $50-100/mo, fragile, requires per-request proxy auth.
- **Cloudflare Worker:** $0/mo, runs on Cloudflare edge (which truthsocial.com
  serves), zero latency overhead, just works.
