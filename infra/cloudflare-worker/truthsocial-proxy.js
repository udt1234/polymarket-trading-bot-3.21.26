/**
 * Cloudflare Worker: Truth Social proxy
 *
 * Forwards requests to truthsocial.com/api/v1/* from a Cloudflare edge IP
 * which truthsocial.com does NOT block (Cloudflare can't easily blocklist
 * itself). This restores the cross-check after Railway's IP got Cloudflare-
 * blocked from reaching truthsocial.com.
 *
 * Usage from the bot:
 *   GET https://<your-worker>.workers.dev/api/v1/accounts/<id>/statuses?limit=40
 *   Header: x-proxy-key: <SHARED_SECRET set in Worker env>
 *
 * The Worker strips its own host and rewrites the upstream URL to
 * truthsocial.com, copies query params and a small allowlist of headers,
 * forwards the response body and JSON-relevant headers back. No data is
 * stored anywhere on the Worker — pure passthrough.
 *
 * Free tier: 100,000 requests/day. Bot needs ~12/hr = 288/day. 99.7% headroom.
 *
 * Deploy: see infra/cloudflare-worker/DEPLOY.md
 */

const UPSTREAM_HOST = "truthsocial.com";
const ALLOWED_PATH_PREFIXES = ["/api/v1/"];
// Methods we forward. Truth Social public API is GET-only for our use case.
const ALLOWED_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export default {
  async fetch(request, env, ctx) {
    // Auth check: caller must present x-proxy-key matching the secret we
    // configure in the Cloudflare dashboard. Without this, anyone who
    // discovers the Worker URL can use your free tier.
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

    const reqUrl = new URL(request.url);
    if (!ALLOWED_PATH_PREFIXES.some((p) => reqUrl.pathname.startsWith(p))) {
      return jsonError(403, `Path ${reqUrl.pathname} not on allowlist`);
    }

    // Build upstream URL. Path + query are forwarded verbatim.
    const upstreamUrl = new URL(reqUrl.pathname + reqUrl.search, `https://${UPSTREAM_HOST}`);

    // Forward only safe headers. Drop cookies, host, anything that could leak
    // identity from the dashboard or our origin.
    const forwardHeaders = new Headers();
    forwardHeaders.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36");
    forwardHeaders.set("Accept", request.headers.get("Accept") || "application/json");
    forwardHeaders.set("Accept-Language", "en-US,en;q=0.9");
    forwardHeaders.set("Referer", `https://${UPSTREAM_HOST}/`);
    forwardHeaders.set("Origin", `https://${UPSTREAM_HOST}`);

    let upstreamResponse;
    try {
      upstreamResponse = await fetch(upstreamUrl.toString(), {
        method: request.method,
        headers: forwardHeaders,
        // Cloudflare-specific: fewer retries on connection issues, longer on slow upstream.
        cf: { cacheTtl: 0, cacheEverything: false },
      });
    } catch (err) {
      return jsonError(502, `Upstream fetch failed: ${String(err).slice(0, 200)}`);
    }

    // Echo upstream status + body. Strip cookies & cache control on response.
    const respHeaders = new Headers();
    const ct = upstreamResponse.headers.get("Content-Type");
    if (ct) respHeaders.set("Content-Type", ct);
    respHeaders.set("X-Proxy-Upstream", "truthsocial.com");
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
