"""Phase 14 - repair bracket coverage in the frozen raw trade archive.

Why this exists
---------------
canonical/prices only contains brackets that have trades in
_raw_imports/api_trades_v2/. Two defects left the WINNING bracket out of that
archive for 134 of 244 Elon auctions (Trump was unaffected):

  1. Late-added brackets. 10_fresh_gamma_rebuild pulled its bracket list from a
     cached Gamma snapshot. Polymarket extends the ladder mid-auction as the
     count moves, so brackets added after the snapshot were never pulled -- and
     the winner is disproportionately a late-added bracket, because it is the
     one the count moved toward.
  2. Truncated pulls. Several recovered brackets stop at an exact multiple of
     the 500-row page size (3500 is the common value), i.e. pagination aborted
     early. data-api returns newest-first, so a truncated bracket is missing the
     START of the auction -- precisely the checkpoints an early-window model is
     scored at.

This script re-derives the authoritative bracket set from a FRESH Gamma pull per
auction, then pulls any bracket that is absent from raw or whose row count is a
suspicious multiple of the page size, and rewrites that bracket's rows.

Run 04_build_prices.py afterwards; prices is derived and must be rebuilt.

Usage:
  python -u scripts/canonical/14_repair_bracket_coverage.py --dry-run
  python -u scripts/canonical/14_repair_bracket_coverage.py
  python -u scripts/canonical/14_repair_bracket_coverage.py --handle elonmusk
  python -u scripts/canonical/14_repair_bracket_coverage.py --refresh-gamma

Idempotent and resumable: Gamma events are cached per slug, and a second run
finds nothing to pull.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _canon import CANON, HANDLES, RAW_DIR, load_partitioned, normalize_bucket  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com/trades"
PAGE_LIMIT = 500
RATE_LIMIT_SEC = 0.1  # global floor between API calls, enforced across workers
DEFAULT_WORKERS = 6
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 4
EVENT_CACHE = CANON / "_gamma_cache" / "events_by_slug"
REPORT = CANON / "_audit" / "bracket_coverage_repair.json"

# One auction per worker. Each worker owns its own raw parquet, so there is no
# shared write; only the HTTP budget is shared, hence the global throttle.
_throttle = threading.Semaphore(1)
_last_call = [0.0]


def _pace():
    """Global floor between outbound API calls, whatever the worker count."""
    with _throttle:
        wait = RATE_LIMIT_SEC - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def http_get(url: str, timeout: int = 30):
    last = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            _pace()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (canonical-repair)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            last = e
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last  # pragma: no cover


def fetch_event(slug: str, refresh: bool = False) -> dict | None:
    EVENT_CACHE.mkdir(parents=True, exist_ok=True)
    cache = EVENT_CACHE / f"{slug}.json"
    if cache.exists() and not refresh:
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            return d or None
        except Exception:
            pass
    try:
        d = http_get(f"{GAMMA}/events?slug={slug}")
    except Exception:
        return None
    ev = d[0] if isinstance(d, list) and d else None
    cache.write_text(json.dumps(ev or {}), encoding="utf-8")
    return ev


def extract_brackets(ev: dict) -> list[dict]:
    out = []
    for m in ev.get("markets", []) or []:
        label = normalize_bucket(m.get("groupItemTitle") or "")
        cid = str(m.get("conditionId") or "")
        if not label or not cid:
            continue
        try:
            toks = json.loads(m.get("clobTokenIds") or "[]")
        except Exception:
            toks = []
        try:
            outs = json.loads(m.get("outcomes") or "[]")
        except Exception:
            outs = []
        yes = no = ""
        for i, o in enumerate(outs):
            if str(o).lower() in ("yes", "1") and i < len(toks):
                yes = str(toks[i])
            elif str(o).lower() in ("no", "0") and i < len(toks):
                no = str(toks[i])
        out.append({"label": label, "cid": cid, "yes": yes, "no": no,
                    "outcome_prices_raw": m.get("outcomePrices") or ""})
    return out


def fetch_all_trades(condition_id: str) -> tuple[list[dict], bool]:
    """Page to exhaustion. Returns (trades, complete). complete=False means the
    pull stopped early, so the caller must not treat the count as authoritative."""
    out: list[dict] = []
    offset = 0
    while True:
        try:
            page = http_get(f"{DATA_API}?market={condition_id}&limit={PAGE_LIMIT}&offset={offset}")
        except urllib.error.HTTPError as e:
            # 400 = this market never traded on data-api. That is an answer, not a failure.
            return (out, e.code == 400)
        except Exception:
            return (out, False)
        if not isinstance(page, list):
            return (out, False)
        out.extend(page)
        if len(page) < PAGE_LIMIT:
            return (out, True)
        offset += PAGE_LIMIT


def trades_to_frame(trades: list[dict], br: dict, handle: str, template: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    df["_bucket"] = br["label"]
    df["_bracket_yes_token"] = br["yes"]
    df["_bracket_no_token"] = br["no"]
    df["_outcome_resolved"] = br["outcome_prices_raw"]
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True, errors="coerce")
    df["handle"] = handle
    if "notional" not in df.columns:
        df["notional"] = df["size"].astype(float) * df["price"].astype(float)
    df["conditionId"] = br["cid"]
    for c in template.columns:
        if c not in df.columns:
            df[c] = None
    return df[template.columns]


def repair_auction(slug: str, handle: str, refresh_gamma: bool, dry_run: bool) -> dict:
    path = RAW_DIR / f"{slug}.parquet"
    res = {"slug": slug, "handle": handle, "status": "ok", "pulled": [], "added_rows": 0,
           "missing_from_gamma": [], "unpullable": []}
    if not path.exists():
        res["status"] = "no_raw_file"
        return res
    raw = pd.read_parquet(path)
    if not len(raw):
        res["status"] = "empty_raw_file"
        return res

    ev = fetch_event(slug, refresh=refresh_gamma)
    if not ev:
        res["status"] = "no_gamma_event"
        return res
    brackets = extract_brackets(ev)
    if not brackets:
        res["status"] = "no_gamma_markets"
        return res

    counts = raw.groupby(raw["conditionId"].astype(str)).size().to_dict()
    todo = []
    for br in brackets:
        have = counts.get(br["cid"], 0)
        if have == 0:
            todo.append((br, have, "absent"))
        elif have % PAGE_LIMIT == 0:
            # a complete pull ends on a short page, so an exact page multiple is
            # almost always a truncated pull. Verify against the API.
            todo.append((br, have, "suspect_truncated"))
    if not todo:
        res["status"] = "already_complete"
        return res
    if dry_run:
        res["status"] = "would_repair"
        res["pulled"] = [{"bucket": b["label"], "cid": b["cid"], "have": h, "why": w}
                         for b, h, w in todo]
        return res

    frames = []
    drop_cids = set()
    for br, have, why in todo:
        trades, complete = fetch_all_trades(br["cid"])
        if not trades:
            if have == 0:
                res["unpullable"].append({"bucket": br["label"], "cid": br["cid"],
                                          "why": why, "complete": complete})
            continue
        if why == "suspect_truncated" and len(trades) <= have:
            # Either it was not truncated after all, or this pull came back
            # short. Never trade a bigger archive for a smaller one.
            continue
        frames.append(trades_to_frame(trades, br, handle, raw))
        drop_cids.add(br["cid"])
        res["pulled"].append({"bucket": br["label"], "cid": br["cid"], "have": have,
                              "fetched": len(trades), "why": why, "complete": complete})
    if not frames:
        res["status"] = "nothing_recovered" if res["unpullable"] else "already_complete"
        return res

    kept = raw[~raw["conditionId"].astype(str).isin(drop_cids)]
    combined = pd.concat([kept] + frames, ignore_index=True)
    combined = combined.sort_values("ts").reset_index(drop=True)
    if "hours_in" in combined.columns and combined["ts"].notna().any():
        t0 = combined["ts"].min()
        combined["hours_in"] = (combined["ts"] - t0).dt.total_seconds() / 3600.0
    combined.to_parquet(path, index=False)
    res["status"] = "repaired"
    res["added_rows"] = len(combined) - len(raw)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", choices=HANDLES, help="limit to one handle")
    ap.add_argument("--dry-run", action="store_true", help="survey only, write nothing")
    ap.add_argument("--refresh-gamma", action="store_true", help="bypass the per-slug event cache")
    ap.add_argument("--limit", type=int, help="process at most N auctions (smoke test)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help="auctions repaired concurrently (each owns its own raw file)")
    args = ap.parse_args()

    handles = [args.handle] if args.handle else HANDLES
    results = []
    t0 = time.time()
    for handle in handles:
        auc = load_partitioned("auctions", handle)
        if not len(auc):
            print(f"[14] {handle}: no auctions, skipping")
            continue
        slugs = auc["auction_slug"].dropna().astype(str).unique().tolist()
        if args.limit:
            slugs = slugs[:args.limit]
        print(f"[14] {handle}: {len(slugs)} auctions, {args.workers} workers "
              f"({'DRY RUN' if args.dry_run else 'REPAIR'})", flush=True)
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futs = {pool.submit(repair_auction, s, handle, args.refresh_gamma, args.dry_run): s
                    for s in slugs}
            for fut in as_completed(futs):
                slug = futs[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"slug": slug, "handle": handle, "status": f"error_{type(e).__name__}",
                         "pulled": [], "added_rows": 0, "missing_from_gamma": [], "unpullable": []}
                results.append(r)
                done += 1
                if r["status"] not in ("already_complete", "ok"):
                    bits = ", ".join(f"{p['bucket']}({p.get('have')}->{p.get('fetched','?')})"
                                     for p in r["pulled"]) or "-"
                    print(f"  [{done}/{len(slugs)}] {slug[:46]:<48} {r['status']:<18} {bits}",
                          flush=True)
                elif done % 25 == 0:
                    print(f"  [{done}/{len(slugs)}] ... {time.time()-t0:.0f}s elapsed", flush=True)

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    total_added = sum(r["added_rows"] for r in results)
    unpullable = [r for r in results if r["unpullable"]]

    print(f"\n[14] DONE in {(time.time()-t0)/60:.1f} min")
    print(f"  status: {by_status}")
    print(f"  rows added to raw archive: {total_added:,}")
    if unpullable:
        print(f"  brackets Gamma lists but data-api has no trades for "
              f"(genuine data-availability limit, {len(unpullable)} auctions):")
        for r in unpullable[:20]:
            for u in r["unpullable"]:
                print(f"    {r['slug'][:44]:<46} {u['bucket']}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(
        {"dry_run": args.dry_run, "by_status": by_status, "rows_added": total_added,
         "results": results}, indent=2, default=str), encoding="utf-8")
    print(f"  report: {REPORT}")
    if not args.dry_run:
        print("\n  NEXT: python -u scripts/canonical/04_build_prices.py   (prices is derived, rebuild it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
