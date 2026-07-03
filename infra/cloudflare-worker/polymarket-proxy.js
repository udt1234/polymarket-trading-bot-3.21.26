/**
 * Cloudflare Worker: Polymarket API proxy (all 3 hosts)
 *
 * Routes ALL Polymarket bot traffic through a Cloudflare edge IP, defeating
 * the geoblock that returns 403 to Railway's US-based IPs when placing
 * real-money orders.
 *
 * Why this design (one Worker, three upstreams):
 *   - Single proxy URL/secret to manage instead of three
 *   - Adding a new Polymarket host later = one line in UPSTREAMS
 *   - Bot just rewrites the base URL — same path, same headers, same body,
 *     same auth flow. The CLOB SDK's L1/L2 signing works unchanged because
 *     the signature is over the request body, not the host header.
 *
 * Routing (path-prefix based):
 *   /clob/*       -> https://clob.polymarket.com/*
 *   /gamma/*      -> https://gamma-api.polymarket.com/*
 *   /xtracker/*   -> https://xtracker.polymarket.com/*
 *
 * Usage from the bot:
 *   - Set POLYMARKET_PROXY_URL = https://polymarket-proxy.<sub>.workers.dev
 *   - Set POLYMARKET_PROXY_KEY = <SHARED_SECRET from this Worker's env>
 *   - The bot's URL builders prepend POLYMARKET_PROXY_URL/<upstream>/ when
 *     the env var is set; otherwise they hit Polymarket directly.
 *
 * Methods forwarded: GET, HEAD, OPTIONS, POST, PUT, DELETE
 *   POST/PUT/DELETE are required for CLOB order placement, cancellation,
 *   and API-key management. The CLOB SDK signs every request with the
 *   trader's private key, so the Worker passing the body through is safe —
 *   only the trader could have produced a valid signature.
 *
 * Free tier: 100,000 requests/day. Bot uses ~5,000/day across all 3 hosts
 *   (cycles every 5 min × ~17 calls/cycle × 24h). 95% headroom.
 *
 * Headers preserved:
 *   - Authorization, POLY_ADDRESS, POLY_SIGNATURE, POLY_TIMESTAMP,
 *     POLY_API_KEY, POLY_PASSPHRASE, POLY_NONCE — all CLOB auth headers
 *   - Content-Type, Accept, Accept-Language, User-Agent
 *
 * Headers dropped (security/privacy):
 *   - Cookie, Set-Cookie, CF-* (Cloudflare internal), Railway-specific
 *
 * Deploy: see infra/cloudflare-worker/DEPLOY_POLYMARKET.md
 */

const UPSTREAMS = {
  clob:     "https://clob.polymarket.com",
  gamma:    "https://gamma-api.polymarket.com",
  xtracker: "https://xtracker.polymarket.com",
};

const ALLOWED_METHODS = new Set(["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE"]);

// Headers the bot needs forwarded to Polymarket. Anything not on this list
// is dropped to avoid leaking Cloudflare/Railway internals upstream.
const FORWARDABLE_REQUEST_HEADERS = new Set([
  "accept",
  "accept-language",
  "content-type",
  "user-agent",
  // Polymarket CLOB auth headers (L1 = wallet sig, L2 = API key sig)
  "authorization",
  "poly_address",
  "poly_signature",
  "poly_timestamp",
  "poly_api_key",
  "poly_passphrase",
  "poly_nonce",
]);

export default {
  async fetch(request, env, ctx) {
    // ---- Auth check ----
    const presented = request.headers.get("x-proxy-key") || "";
    const expected = env.PROXY_KEY || "";
    if (!expected) {
      return jsonError(500, "Worker misconfigured: PROXY_KEY env var not set");
    }
    if (presented !== expected) {
      return jsonError(401, "Invalid or missing x-proxy-key");
    }

    if (!ALLOWED_METHODS.has(request.method)) {
      return jsonError(405, `Method ${request.method} not allowed`);
    }

    // ---- Resolve upstream from first path segment ----
    const reqUrl = new URL(request.url);
    const pathParts = reqUrl.pathname.split("/").filter(Boolean);
    if (pathParts.length === 0) {
      return jsonError(404, "No upstream specified. Use /clob/*, /gamma/*, or /xtracker/*");
    }
    const upstreamKey = pathParts[0];
    const upstreamHost = UPSTREAMS[upstreamKey];
    if (!upstreamHost) {
      return jsonError(404, `Unknown upstream '${upstreamKey}'. Allowed: ${Object.keys(UPSTREAMS).join(", ")}`);
    }

    // Strip the upstream prefix from the path. /clob/foo/bar -> /foo/bar
    const upstreamPath = "/" + pathParts.slice(1).join("/");
    const upstreamUrl = new URL(upstreamPath + reqUrl.search, upstreamHost);

    // ---- Build forward headers (allowlist) ----
    const forwardHeaders = new Headers();
    for (const [name, value] of request.headers.entries()) {
      if (FORWARDABLE_REQUEST_HEADERS.has(name.toLowerCase())) {
        forwardHeaders.set(name, value);
      }
    }
    // If caller didn't set a User-Agent, fake a browser one so Polymarket
    // doesn't profile us as a generic httpx client.
    if (!forwardHeaders.has("user-agent")) {
      forwardHeaders.set(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
      );
    }

    // ---- Forward body for non-GET/HEAD requests ----
    let body = undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await request.arrayBuffer();
    }

    // ---- Fire upstream request ----
    let upstreamResponse;
    try {
      upstreamResponse = await fetch(upstreamUrl.toString(), {
        method: request.method,
        headers: forwardHeaders,
        body,
        // Do NOT cache CLOB responses — order book changes per second
        cf: { cacheTtl: 0, cacheEverything: false },
      });
    } catch (err) {
      return jsonError(502, `Upstream fetch failed: ${String(err).slice(0, 200)}`);
    }

    // ---- Echo response (drop cookies, preserve content-type) ----
    const respHeaders = new Headers();
    for (const [name, value] of upstreamResponse.headers.entries()) {
      const lower = name.toLowerCase();
      // Drop cookies and upstream cache headers — bot should never receive these
      if (lower === "set-cookie" || lower === "cookie") continue;
      if (lower.startsWith("cf-")) continue;
      respHeaders.set(name, value);
    }
    respHeaders.set("X-Proxy-Upstream", upstreamKey);
    respHeaders.set("X-Proxy-Status", String(upstreamResponse.status));

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: respHeaders,
    });
  },
};

function jsonError(status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
