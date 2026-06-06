"""
Fresh canonical rebuild from Gamma + data-api only. ZERO whale_analysis.

Pipeline:
  1. Paginate Gamma /events?tag_id=972 (Tweet Markets) for ALL closed+open
  2. Filter to Elon + Trump slug patterns
  3. For each event, extract bracket list with conditionId + token_ids from
     event.markets (Gamma authoritative source)
  4. For each bracket conditionId, pull all trades from data-api /trades
  5. Save one parquet per auction at canonical/_raw_imports/api_trades_v2/

Output: clean per-auction trade files ready for 03/04 builders.

Idempotent: skips already-pulled files. Force re-pull by deleting the parquet.
Rate limit: 0.5s between data-api calls.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
OUT_DIR = CANON / "_raw_imports" / "api_trades_v2"
EVENTS_CACHE = CANON / "_gamma_cache" / "tweet_markets_events.json"

GAMMA = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com/trades"
PAGE_LIMIT = 500
RATE_LIMIT_SEC = 0.5
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 4

ELON_SLUG_PATTERNS = ["elon-musk-of-tweets", "of-elon-musk-tweets", "elon-musk-tweets-between"]
TRUMP_SLUG_PATTERNS = ["donald-trump-of-truth-social-posts", "donald-trump-of-tweets",
                       "president-trump-of-tweets", "of-donald-trump-tweets", "of-donald-trump-truth"]


def _http_get(url: str, timeout: int = 30):
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (gamma-rebuild)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(2 ** attempt); continue
            raise
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt); continue
            raise


def discover_events(force: bool = False) -> list[dict]:
    """Paginate Gamma for all Tweet Markets events. Cache result."""
    if EVENTS_CACHE.exists() and not force:
        return json.loads(EVENTS_CACHE.read_text())
    print("[discover] paginating Gamma /events?tag_id=972...")
    all_events = []
    for closed in [True, False]:
        for offset in range(0, 3000, 100):
            data = _http_get(f"{GAMMA}/events?tag_id=972&closed={str(closed).lower()}&limit=100&offset={offset}")
            if not data: break
            all_events.extend(data)
            if len(data) < 100: break
            time.sleep(0.1)
    seen = set(); unique = []
    for e in all_events:
        if e["id"] not in seen:
            seen.add(e["id"]); unique.append(e)
    EVENTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_CACHE.write_text(json.dumps(unique))
    return unique


def filter_handle(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split events into (elon, trump) by slug pattern."""
    elon = [e for e in events if any(p in e.get("slug", "") for p in ELON_SLUG_PATTERNS)]
    trump = [e for e in events if any(p in e.get("slug", "") for p in TRUMP_SLUG_PATTERNS)]
    return elon, trump


def extract_brackets(event: dict) -> list[dict]:
    """From Gamma event.markets, return list of {bucket_label, condition_id, yes_token, no_token}."""
    out = []
    for m in event.get("markets", []):
        label = (m.get("groupItemTitle") or "").strip()
        cid = m.get("conditionId") or ""
        # outcomes / clob token ids — try multiple key shapes
        clob_tokens = m.get("clobTokenIds") or "[]"
        try:
            tokens = json.loads(clob_tokens) if isinstance(clob_tokens, str) else clob_tokens
        except Exception:
            tokens = []
        outcomes = m.get("outcomes") or "[]"
        try:
            outs = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        except Exception:
            outs = []
        # match outcome name to token
        yes_token = no_token = ""
        for i, o in enumerate(outs):
            if str(o).lower() in ("yes", "1"):
                if i < len(tokens): yes_token = str(tokens[i])
            elif str(o).lower() in ("no", "0"):
                if i < len(tokens): no_token = str(tokens[i])
        out.append({
            "bucket_label": label,
            "condition_id": cid,
            "yes_token": yes_token,
            "no_token": no_token,
            "outcome_prices_raw": m.get("outcomePrices") or "",
        })
    return out


def fetch_trades_paginated(condition_id: str) -> list[dict]:
    """Page through ALL trades for one market via data-api."""
    out = []
    offset = 0
    while True:
        page = _http_get(f"{DATA_API}?market={condition_id}&limit={PAGE_LIMIT}&offset={offset}")
        if not isinstance(page, list): break
        out.extend(page)
        if len(page) < PAGE_LIMIT: break
        offset += PAGE_LIMIT
        time.sleep(RATE_LIMIT_SEC)
    return out


def process_event(handle: str, event: dict, force: bool = False) -> dict:
    slug = event["slug"]
    out_path = OUT_DIR / f"{slug}.parquet"
    if out_path.exists() and not force:
        return {"slug": slug, "status": "skipped", "n_trades": 0}

    brackets = extract_brackets(event)
    if not brackets:
        return {"slug": slug, "status": "empty", "n_trades": 0, "msg": "no markets in event"}

    all_rows = []
    failed = []
    bracket_meta = {}  # label -> (cid, yes, no)
    for b in brackets:
        cid = b["condition_id"]
        label = b["bucket_label"]
        bracket_meta[label] = b
        if not cid:
            failed.append(f"{label}(no_cid)")
            continue
        try:
            trades = fetch_trades_paginated(cid)
        except Exception as e:
            failed.append(f"{label}({type(e).__name__})")
            time.sleep(RATE_LIMIT_SEC)
            continue
        for t in trades:
            t["_bucket"] = label
            t["_bracket_yes_token"] = b["yes_token"]
            t["_bracket_no_token"] = b["no_token"]
            t["_outcome_resolved"] = b["outcome_prices_raw"]
        all_rows.extend(trades)
        time.sleep(RATE_LIMIT_SEC)

    if not all_rows:
        return {"slug": slug, "status": "empty", "n_trades": 0, "msg": f"all {len(brackets)} failed"}

    df = pd.DataFrame(all_rows)
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True, errors="coerce")
    df["handle"] = handle
    if "notional" not in df.columns:
        df["notional"] = df["size"].astype(float) * df["price"].astype(float)
    min_ts = df["ts"].min()
    df["hours_in"] = (df["ts"] - min_ts).dt.total_seconds() / 3600.0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return {
        "slug": slug,
        "status": "partial" if failed else "fetched",
        "n_trades": len(df),
        "n_brackets_ok": df["_bucket"].nunique(),
        "n_brackets_failed": len(failed),
        "msg": f"failed: {failed[:3]}" if failed else "",
    }


def main():
    events = discover_events()
    elon, trump = filter_handle(events)
    total_brackets = sum(len(e.get("markets", [])) for e in elon + trump)
    print(f"[discover] elon={len(elon)} trump={len(trump)} total_brackets={total_brackets}")
    print(f"[fetch] estimated runtime ~{total_brackets * 1.5 / 60:.0f} min")
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    counters = {"fetched": 0, "partial": 0, "skipped": 0, "empty": 0}
    items = [("elonmusk", e) for e in elon] + [("realDonaldTrump", e) for e in trump]
    for i, (handle, ev) in enumerate(items, 1):
        result = process_event(handle, ev)
        counters[result["status"]] = counters.get(result["status"], 0) + 1
        if i % 10 == 0 or i == len(items):
            el = time.time() - t0
            eta = (el / i) * (len(items) - i) if i else 0
            print(f"[fetch] {i}/{len(items)} in {el:.0f}s "
                  f"(skip={counters['skipped']} fetched={counters['fetched']} "
                  f"partial={counters['partial']} empty={counters['empty']}, "
                  f"ETA {eta/60:.1f}min) last={result['slug'][:40]} "
                  f"n={result['n_trades']}", flush=True)

    print()
    print(f"[fetch] DONE in {(time.time()-t0)/60:.1f} min")
    print(f"  counters: {counters}")
    print(f"  output: {OUT_DIR}")


if __name__ == "__main__":
    main()
