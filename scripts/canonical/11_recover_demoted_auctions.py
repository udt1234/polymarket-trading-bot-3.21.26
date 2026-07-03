"""
Recover the 134 demoted Elon auctions (resolution_status='resolved_yes_gamma_bracket_mismatch').

Root cause: vAI's cached Gamma events snapshot was taken before Polymarket
added some brackets (especially the winning one). The original pull missed
those late-added brackets.

Fix:
  1. For each demoted auction, re-fetch /events?slug=<slug> FRESH (no cache)
  2. Find brackets present in Gamma but missing from our raw api_trades_v2
  3. Pull /trades for only the missing bracket conditionIds
  4. APPEND new trades to existing api_trades_v2/{slug}.parquet
  5. Optionally also re-check 'high' confidence auctions for the same gap

Idempotent.
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
RAW_DIR = CANON / "_raw_imports" / "api_trades_v2"

GAMMA = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com/trades"
PAGE_LIMIT = 500
RATE_LIMIT_SEC = 0.5
RETRY_STATUSES = {400, 429, 500, 502, 503, 504}
MAX_RETRIES = 6


def _http_get(url: str, timeout: int = 30):
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (recover)"})
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


def fetch_fresh_event(slug: str) -> list | None:
    """No cache — always fresh hit on Gamma."""
    try:
        return _http_get(f"{GAMMA}/events?slug={slug}")
    except Exception:
        return None


def extract_brackets(event: dict) -> list[dict]:
    out = []
    for m in event.get("markets", []):
        label = (m.get("groupItemTitle") or "").strip()
        cid = m.get("conditionId") or ""
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
        yes_token = no_token = ""
        for i, o in enumerate(outs):
            if str(o).lower() in ("yes", "1") and i < len(tokens):
                yes_token = str(tokens[i])
            elif str(o).lower() in ("no", "0") and i < len(tokens):
                no_token = str(tokens[i])
        out.append({
            "bucket_label": label,
            "condition_id": cid,
            "yes_token": yes_token,
            "no_token": no_token,
            "outcome_prices_raw": m.get("outcomePrices") or "",
        })
    return out


def fetch_trades_paginated(condition_id: str) -> list[dict]:
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


def recover_auction(slug: str) -> dict:
    raw_path = RAW_DIR / f"{slug}.parquet"
    if not raw_path.exists():
        return {"slug": slug, "status": "no_raw"}
    existing = pd.read_parquet(raw_path)
    existing_cids = set(existing["conditionId"].unique())
    existing_buckets = set(existing["_bucket"].unique())

    ev_data = fetch_fresh_event(slug)
    if not ev_data:
        return {"slug": slug, "status": "gamma_err"}
    ev = ev_data[0] if isinstance(ev_data, list) and ev_data else None
    if not ev:
        return {"slug": slug, "status": "no_event"}

    brackets = extract_brackets(ev)
    missing = [b for b in brackets if b["condition_id"] and b["condition_id"] not in existing_cids]

    if not missing:
        return {"slug": slug, "status": "already_complete", "n_brackets_total": len(brackets)}

    new_rows = []
    failed = []
    for b in missing:
        try:
            trades = fetch_trades_paginated(b["condition_id"])
        except Exception as e:
            failed.append(f"{b['bucket_label']}({type(e).__name__})")
            time.sleep(RATE_LIMIT_SEC)
            continue
        for t in trades:
            t["_bucket"] = b["bucket_label"]
            t["_bracket_yes_token"] = b["yes_token"]
            t["_bracket_no_token"] = b["no_token"]
            t["_outcome_resolved"] = b["outcome_prices_raw"]
        new_rows.extend(trades)
        time.sleep(RATE_LIMIT_SEC)

    if not new_rows:
        return {"slug": slug, "status": "no_new_trades", "n_missing": len(missing), "n_failed": len(failed)}

    new_df = pd.DataFrame(new_rows)
    new_df["ts"] = pd.to_datetime(new_df["timestamp"], unit="s", utc=True, errors="coerce")
    new_df["handle"] = existing["handle"].iloc[0] if "handle" in existing.columns else ""
    if "notional" not in new_df.columns:
        new_df["notional"] = new_df["size"].astype(float) * new_df["price"].astype(float)
    min_ts = new_df["ts"].min()
    new_df["hours_in"] = (new_df["ts"] - min_ts).dt.total_seconds() / 3600.0

    # align cols
    for c in existing.columns:
        if c not in new_df.columns:
            new_df[c] = None
    new_df = new_df[existing.columns]

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined.to_parquet(raw_path, index=False)
    return {
        "slug": slug,
        "status": "recovered",
        "n_missing_brackets": len(missing),
        "n_new_trades": len(new_df),
        "n_failed_brackets": len(failed),
    }


def main():
    # find all demoted Elon auctions
    auc_files = sorted((CANON / "auctions" / "elonmusk").glob("*.parquet"))
    auc = pd.concat([pd.read_parquet(p) for p in auc_files], ignore_index=True)
    demoted = auc[auc["resolution_status"] == "resolved_yes_gamma_bracket_mismatch"]
    print(f"[recover] demoted Elon auctions to retry: {len(demoted)}")

    t0 = time.time()
    counters = {"recovered": 0, "already_complete": 0, "no_raw": 0,
                "gamma_err": 0, "no_event": 0, "no_new_trades": 0}
    total = len(demoted)
    for i, (_, a) in enumerate(demoted.iterrows(), 1):
        result = recover_auction(a["auction_slug"])
        counters[result["status"]] = counters.get(result["status"], 0) + 1
        if i % 10 == 0 or i == total:
            el = time.time() - t0
            eta = (el / i) * (total - i) if i else 0
            extras = ""
            if result["status"] == "recovered":
                extras = f" (+{result.get('n_new_trades', 0)} trades, {result.get('n_missing_brackets', 0)} brackets)"
            print(f"[recover] {i}/{total} in {el:.0f}s "
                  f"(rec={counters['recovered']} done={counters['already_complete']} "
                  f"err={counters['gamma_err']+counters['no_event']}) "
                  f"ETA {eta/60:.1f}min last={a['auction_slug'][:40]}{extras}", flush=True)

    print()
    print(f"[recover] DONE in {(time.time()-t0)/60:.1f} min")
    print(f"  counters: {counters}")


if __name__ == "__main__":
    main()
