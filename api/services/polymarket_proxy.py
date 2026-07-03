"""Single source of truth for Polymarket API host rewriting.

Why this module exists
----------------------
Polymarket geoblocks Railway's US IP for real-money order placement (CFTC
compliance). We work around it with a Cloudflare Worker (deployed from
infra/cloudflare-worker/polymarket-proxy.js) that forwards traffic through
a CF edge IP.

This module is the ONLY place in the codebase that knows about the proxy.
Every Polymarket caller (CLOB executor, gamma data fetcher, xtracker data
fetcher) routes through `rewrite_url()` or `proxy_host()`.

Env vars
--------
POLYMARKET_PROXY_URL — Worker base URL (e.g. https://polymarket-proxy.foo.workers.dev)
                       When unset, calls go direct to Polymarket (paper mode safe).
POLYMARKET_PROXY_KEY — Shared secret that must match Worker's PROXY_KEY env var.

Failure modes (intentional)
---------------------------
- If POLYMARKET_PROXY_URL is set but POLYMARKET_PROXY_KEY is missing, raise
  on first use. We never silently fall back to direct (which would 403 and
  burn money on rejected orders).
- If POLYMARKET_PROXY_URL is unset, every caller behaves exactly as before.
  Paper mode, local dev, and the test suite all continue to work.

Routing
-------
The Worker uses path-prefix routing: /clob/* /gamma/* /xtracker/* — so
the rewrites here are:
  https://clob.polymarket.com/foo       -> {PROXY}/clob/foo
  https://gamma-api.polymarket.com/foo  -> {PROXY}/gamma/foo
  https://xtracker.polymarket.com/foo   -> {PROXY}/xtracker/foo
"""
from __future__ import annotations
import os
from urllib.parse import urlparse, urlunparse

# Upstream hosts the proxy knows about. If Polymarket adds a new host
# (e.g. data-api.polymarket.com), add it here AND in the Worker's UPSTREAMS map.
_UPSTREAM_TO_PREFIX = {
    "clob.polymarket.com":     "clob",
    "gamma-api.polymarket.com": "gamma",
    "xtracker.polymarket.com":  "xtracker",
}


def proxy_enabled() -> bool:
    """True when POLYMARKET_PROXY_URL is set in the environment."""
    return bool(os.getenv("POLYMARKET_PROXY_URL", "").strip())


def proxy_base() -> str:
    """Return the proxy base URL with no trailing slash, or '' when disabled."""
    return os.getenv("POLYMARKET_PROXY_URL", "").strip().rstrip("/")


def proxy_key() -> str:
    """Return the x-proxy-key value. Raises if the proxy is enabled but the
    key is missing — fail loudly rather than silently sending unauth'd
    requests that the Worker will 401."""
    if not proxy_enabled():
        return ""
    key = os.getenv("POLYMARKET_PROXY_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "POLYMARKET_PROXY_URL is set but POLYMARKET_PROXY_KEY is missing. "
            "Configure both in Railway env vars or unset the URL."
        )
    return key


def proxy_headers() -> dict[str, str]:
    """Headers to attach to every request that targets the proxy. Empty dict
    when the proxy is disabled — caller can splat into existing headers
    without conditional logic."""
    if not proxy_enabled():
        return {}
    return {"x-proxy-key": proxy_key()}


def rewrite_url(url: str) -> str:
    """Rewrite a direct Polymarket URL to go through the proxy.

    Examples:
        rewrite_url("https://clob.polymarket.com/orders")
            -> "https://proxy.workers.dev/clob/orders" (when proxy enabled)
            -> "https://clob.polymarket.com/orders"    (when proxy disabled)

    Pass-through behavior: if the URL's host isn't a known Polymarket host,
    return it unchanged. This lets callers blindly wrap every outbound URL
    without breaking calls to Slack/Supabase/etc.
    """
    if not proxy_enabled():
        return url
    parsed = urlparse(url)
    prefix = _UPSTREAM_TO_PREFIX.get(parsed.netloc)
    if not prefix:
        return url  # Not a Polymarket host — pass through unchanged
    base = proxy_base()
    # Preserve path, query, and fragment. Prepend /<prefix>.
    new_path = f"/{prefix}{parsed.path}"
    new_parsed = urlparse(base)
    return urlunparse((
        new_parsed.scheme,
        new_parsed.netloc,
        new_parsed.path.rstrip("/") + new_path,
        "",
        parsed.query,
        parsed.fragment,
    ))


def clob_host() -> str:
    """Return the host to pass to py_clob_client.ClobClient(host=...).

    When proxy is enabled, returns the proxy + /clob prefix. ClobClient
    builds all its endpoints as f'{host}{ENDPOINT}', so this puts every
    SDK call through the proxy automatically.
    """
    if not proxy_enabled():
        return "https://clob.polymarket.com"
    return f"{proxy_base()}/clob"


# ---------------------------------------------------------------------------
# httpx helpers — drop-in wrappers for gamma + xtracker callers
# ---------------------------------------------------------------------------
# Pattern: callers replace
#     async with httpx.AsyncClient() as c:
#         r = await c.get("https://gamma-api.polymarket.com/events?...")
# with
#     async with httpx.AsyncClient() as c:
#         r = await pmx_get(c, "https://gamma-api.polymarket.com/events?...")
# pmx_get/pmx_post handle URL rewriting + auth-key header injection
# transparently. When the proxy is disabled, they behave exactly like the
# raw httpx methods.


async def pmx_get(client, url: str, *, params=None, headers=None, **kwargs):
    """Proxy-aware GET. Rewrites Polymarket URLs to the Worker and adds the
    x-proxy-key header. Pass-through for non-Polymarket URLs."""
    final_url = rewrite_url(url)
    final_headers = dict(headers or {})
    final_headers.update(proxy_headers())
    return await client.get(final_url, params=params, headers=final_headers, **kwargs)


async def pmx_post(client, url: str, *, params=None, headers=None, json=None, data=None, **kwargs):
    """Proxy-aware POST. Same semantics as pmx_get."""
    final_url = rewrite_url(url)
    final_headers = dict(headers or {})
    final_headers.update(proxy_headers())
    return await client.post(
        final_url, params=params, headers=final_headers, json=json, data=data, **kwargs
    )


# ---------------------------------------------------------------------------
# Base URL constants (proxy-aware)
# ---------------------------------------------------------------------------
# Callers should import these instead of hard-coding the polymarket.com URLs.
# When the proxy is enabled, these resolve to the Worker URL automatically.
# When disabled, they resolve to the original Polymarket hosts (no behavior
# change for local dev / paper mode / direct callers).
#
# IMPORTANT: x-proxy-key header MUST be sent on every request to these base
# URLs when the proxy is enabled. Use proxy_headers() to splat into your
# httpx headers dict, OR use pmx_get / pmx_post which handle it for you.

def gamma_base() -> str:
    """gamma-api.polymarket.com base URL (proxy-aware)."""
    if not proxy_enabled():
        return "https://gamma-api.polymarket.com"
    return f"{proxy_base()}/gamma"


def xtracker_base() -> str:
    """xtracker.polymarket.com base URL (proxy-aware).

    NOTE: this returns the host root, NOT including '/api'. Many existing
    callers had '/api' baked into their constant — they should keep doing
    `f"{xtracker_base()}/api/..."`. The Worker forwards the path verbatim
    after stripping the /xtracker/ prefix, so /api/foo upstream is preserved.
    """
    if not proxy_enabled():
        return "https://xtracker.polymarket.com"
    return f"{proxy_base()}/xtracker"


def clob_base() -> str:
    """clob.polymarket.com base URL (proxy-aware). For raw httpx callers."""
    if not proxy_enabled():
        return "https://clob.polymarket.com"
    return f"{proxy_base()}/clob"


# ---------------------------------------------------------------------------
# httpx auto-routing patch (THE production path)
# ---------------------------------------------------------------------------
# Monkey-patches httpx.Client.send and httpx.AsyncClient.send to:
#   1. Rewrite any Polymarket-bound URL to the Worker
#   2. Attach the x-proxy-key header
# Applied once at app startup (from api/main.py). After that, every httpx
# call to gamma/xtracker/CLOB anywhere in the codebase is transparently
# routed through the Worker. No per-call-site changes needed.
#
# Why monkey-patch rather than per-call refactor:
#   - The bot has 20+ httpx call sites spread across modules + services
#   - Each call site has slightly different signature shapes (params, body,
#     timeout, etc.) — refactoring each by hand is high-surface, error-prone
#   - A single chokepoint at the httpx layer guarantees no call site is
#     missed and prevents future code paths from leaking direct calls
#   - httpx.Client.send is the universal join point for both sync + async
#     APIs (get/post/put/delete/etc. all go through .send internally)
#
# Idempotency: install_httpx_proxy_patch() is safe to call multiple times.

_PATCHED = False


def install_httpx_proxy_patch() -> None:
    """Monkey-patch httpx so Polymarket URLs auto-route through the Worker.

    No-op when POLYMARKET_PROXY_URL is unset (paper/local mode). Idempotent."""
    global _PATCHED
    if _PATCHED:
        return
    if not proxy_enabled():
        # Don't patch when disabled — keeps stack traces clean in local dev.
        _PATCHED = True
        return

    import httpx
    from urllib.parse import urlparse

    proxy_root = proxy_base()
    proxy_root_host = urlparse(proxy_root).netloc

    _orig_sync_send = httpx.Client.send
    _orig_async_send = httpx.AsyncClient.send

    def _maybe_rewrite(request: "httpx.Request") -> "httpx.Request":
        host = request.url.host
        if host == proxy_root_host:
            # Already targeting the proxy (e.g. retry after rewrite) — only
            # ensure the auth header is present.
            request.headers["x-proxy-key"] = proxy_key()
            return request
        prefix = _UPSTREAM_TO_PREFIX.get(host)
        if not prefix:
            return request  # not a Polymarket host — pass through
        # Rewrite URL: keep path/query, prepend /<prefix>, swap host
        original_path = request.url.path
        new_url = f"{proxy_root}/{prefix}{original_path}"
        if request.url.query:
            new_url = f"{new_url}?{request.url.query.decode('utf-8') if isinstance(request.url.query, bytes) else request.url.query}"
        request.url = httpx.URL(new_url)
        request.headers["x-proxy-key"] = proxy_key()
        # Host header must match the proxy now, otherwise CF gets confused
        request.headers["host"] = proxy_root_host
        return request

    def _patched_sync_send(self, request, **kwargs):
        request = _maybe_rewrite(request)
        return _orig_sync_send(self, request, **kwargs)

    async def _patched_async_send(self, request, **kwargs):
        request = _maybe_rewrite(request)
        return await _orig_async_send(self, request, **kwargs)

    httpx.Client.send = _patched_sync_send
    httpx.AsyncClient.send = _patched_async_send
    _PATCHED = True


def is_httpx_patched() -> bool:
    """Diagnostic: whether install_httpx_proxy_patch() has actually patched."""
    return _PATCHED and proxy_enabled()
