"""
Recovery v2 — simpler, faster, with sane backoff.

For each demoted auction:
  1. Fresh Gamma /events?slug=<slug>
  2. Diff brackets vs existing parquet
  3. For each missing bracket: pull /trades with SHORT retry (3 tries, 1s/2s/4s)
  4. Skip silently on persistent failure (don't burn time)

Faster than v11 because:
  - 3 retries max (was 6), exponential 1/2/4s (was 2/4/8/16/32/64s)
  - No 400 in retry set — 400 means market doesn't exist on data-api, retrying won't help
  - 0.1s base rate limit (was 0.5s) — API handled 0.3s in earlier successful runs
  - Progress every 5 auctions (was 10) for faster feedback
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
RATE_LIMIT_SEC = 0.15
RETRY_STATUSES = {429, 500, 502, 503, 504}  # NOT 400 — 400 is permanent
MAX_RETRIES = 3


def _http_get(url: str, timeout: int = 20):
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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


def fetch_trades_paginated(condition_id: str) -> list[dict]:
    out, offset = [], 0
    while True:
        try:
            page = _http_get(f"{DATA_API}?market={condition_id}&limit={PAGE_LIMIT}&offset={offset}")
        except urllib.error.HTTPError as e:
            if e.code == 400:
                # 400 = market never traded on data-api. Skip cleanly.
                return out
            raise
        if not isinstance(page, list): break
        out.extend(page)
        if len(page) < PAGE_LIMIT: break
        offset += PAGE_LIMIT
        time.sleep(RATE_LIMIT_SEC)
    return out


def extract_brackets(event: dict) -> list[dict]:
    out = []
    for m in event.get("markets", []):
        label = (m.get("groupItemTitle") or "").strip()
        cid = m.get("conditionId") or ""
        clob = m.get("clobTokenIds") or "[]"
        try: tokens = json.loads(clob) if isinstance(clob, str) else clob
        except: tokens = []
        outcomes = m.get("outcomes") or "[]"
        try: outs = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        except: outs = []
        yt = nt = ""
        for i, o in enumerate(outs):
            if str(o).lower() in ("yes","1") and i < len(tokens): yt = str(tokens[i])
            elif str(o).lower() in ("no","0") and i < len(tokens): nt = str(tokens[i])
        out.append({"bucket_label": label, "condition_id": cid, "yes_token": yt, "no_token": nt,
                    "outcome_prices_raw": m.get("outcomePrices") or ""})
    return out


def recover_one(slug: str) -> dict:
    raw_path = RAW_DIR / f"{slug}.parquet"
    if not raw_path.exists():
        return {"slug": slug, "status": "no_raw", "added_trades": 0}
    existing = pd.read_parquet(raw_path)
    existing_cids = set(existing["conditionId"].unique())

    try:
        ev_data = _http_get(f"{GAMMA}/events?slug={slug}")
    except Exception as e:
        return {"slug": slug, "status": f"gamma_{type(e).__name__}", "added_trades": 0}
    ev = ev_data[0] if isinstance(ev_data, list) and ev_data else None
    if not ev:
        return {"slug": slug, "status": "no_event", "added_trades": 0}

    brackets = extract_brackets(ev)
    missing = [b for b in brackets if b["condition_id"] and b["condition_id"] not in existing_cids]

    if not missing:
        return {"slug": slug, "status": "already_complete", "added_trades": 0}

    new_rows = []
    n_skip_400 = 0
    n_skip_err = 0
    for b in missing:
        try:
            trades = fetch_trades_paginated(b["condition_id"])
        except urllib.error.HTTPError as e:
            if e.code == 400: n_skip_400 += 1
            else: n_skip_err += 1
            continue
        except Exception:
            n_skip_err += 1; continue
        if not trades:
            continue
        for t in trades:
            t["_bucket"] = b["bucket_label"]
            t["_bracket_yes_token"] = b["yes_token"]
            t["_bracket_no_token"] = b["no_token"]
            t["_outcome_resolved"] = b["outcome_prices_raw"]
        new_rows.extend(trades)
        time.sleep(RATE_LIMIT_SEC)

    if not new_rows:
        return {"slug": slug, "status": "no_trades_found", "added_trades": 0,
                "missing_brackets": len(missing), "skip_400": n_skip_400, "skip_err": n_skip_err}

    new_df = pd.DataFrame(new_rows)
    new_df["ts"] = pd.to_datetime(new_df["timestamp"], unit="s", utc=True, errors="coerce")
    new_df["handle"] = existing["handle"].iloc[0] if "handle" in existing.columns else ""
    if "notional" not in new_df.columns:
        new_df["notional"] = new_df["size"].astype(float) * new_df["price"].astype(float)
    min_ts = new_df["ts"].min()
    new_df["hours_in"] = (new_df["ts"] - min_ts).dt.total_seconds() / 3600.0
    for c in existing.columns:
        if c not in new_df.columns: new_df[c] = None
    new_df = new_df[existing.columns]
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined.to_parquet(raw_path, index=False)
    return {"slug": slug, "status": "recovered", "added_trades": len(new_df),
            "missing_brackets": len(missing), "skip_400": n_skip_400}


def main():
    auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/"auctions/elonmusk").glob("*.parquet"))],
                    ignore_index=True)
    demoted = auc[auc["resolution_status"] == "resolved_yes_gamma_bracket_mismatch"]
    print(f"[v2] {len(demoted)} demoted auctions to retry", flush=True)

    t0 = time.time()
    stats = {"recovered": 0, "already_complete": 0, "no_trades_found": 0, "no_raw": 0, "no_event": 0}
    total_added = 0
    for i, (_, a) in enumerate(demoted.iterrows(), 1):
        r = recover_one(a["auction_slug"])
        key = r["status"] if r["status"] in stats else "errored"
        stats[key] = stats.get(key, 0) + 1
        total_added += r.get("added_trades", 0)
        if i % 5 == 0 or i == len(demoted):
            el = time.time() - t0
            eta = (el/i) * (len(demoted) - i) if i else 0
            print(f"[v2] {i}/{len(demoted)} in {el:.0f}s rec={stats['recovered']} "
                  f"complete={stats.get('already_complete',0)} no_trades={stats.get('no_trades_found',0)} "
                  f"added_trades={total_added} ETA={eta/60:.1f}min last={a['auction_slug'][:40]}", flush=True)

    print(f"\n[v2] DONE in {(time.time()-t0)/60:.1f} min")
    print(f"  stats: {stats}")
    print(f"  total trades added: {total_added}")


if __name__ == "__main__":
    main()
