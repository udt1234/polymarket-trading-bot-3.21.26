"""
Phase 2.5 — Backfill auction resolutions from Polymarket Gamma API.

For every canonical auction with resolution_status != 'resolved_yes',
hit Gamma /events?slug=<auction_slug>, walk all markets, find the one
where outcomePrices=["1","0"] (YES won), record its groupItemTitle as
the winning_bucket and upgrade confidence.

Output: rewrites canonical/auctions/{handle}/{YYYY-MM}.parquet partitions.

Adds new columns:
  gamma_resolution_source  - 'gamma_events_slug' | 'pre_existing' | 'unresolved_in_gamma'
  gamma_winning_bucket     - raw groupItemTitle from Gamma (may differ from whale_analysis bucket label)

Idempotent. Rate-limited (1 req/sec). Caches Gamma responses to avoid re-hits.
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
AUCTIONS_DIR = CANON / "auctions"
CACHE_DIR = CANON / "_gamma_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GAMMA_BASE = "https://gamma-api.polymarket.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (canonical-backfill)"}
RATE_LIMIT_SEC = 0.6  # ~1.6 req/sec, safe for unauthenticated Gamma


def fetch_event(slug: str) -> list | None:
    """Return Gamma events list for a slug, or None on error. Uses local cache."""
    cache_path = CACHE_DIR / f"{slug}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            cache_path.unlink()  # corrupted, refetch

    url = f"{GAMMA_BASE}/events?slug={slug}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        cache_path.write_text(json.dumps(data))
        return data
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(5)
            return fetch_event(slug)  # retry once
        return None
    except Exception:
        return None


def find_yes_winner(event_data: list) -> tuple[str, str]:
    """
    From Gamma event response, find the bracket market that resolved YES.
    Returns (winning_bucket_label, status):
      status: 'resolved_yes' if found, 'no_winner_in_gamma', 'event_not_closed', 'no_event'
    """
    if not event_data or not isinstance(event_data, list):
        return ("", "no_event")
    ev = event_data[0]
    markets = ev.get("markets", [])
    if not markets:
        return ("", "no_event")
    if not ev.get("closed"):
        return ("", "event_not_closed")
    winners = []
    for m in markets:
        op = m.get("outcomePrices", "[]")
        try:
            if isinstance(op, str):
                op = json.loads(op)
            if op == ["1", "0"] or op == [1, 0]:
                bucket_label = m.get("groupItemTitle") or ""
                winners.append(bucket_label)
        except Exception:
            continue
    if len(winners) == 1:
        return (winners[0], "resolved_yes")
    if len(winners) > 1:
        return (", ".join(winners), f"multi_winner_{len(winners)}")
    return ("", "no_winner_in_gamma")


def normalize_bucket(b: str) -> str:
    """Normalize bucket label for comparison (strip whitespace, unify dash chars)."""
    if not b:
        return ""
    return b.strip().replace("–", "-").replace("—", "-").replace("−", "-")


def main(handle: str | None = None) -> int:
    handles = [handle] if handle else ["realDonaldTrump", "elonmusk"]
    for h in handles:
        print(f"\n[backfill] handle={h}")
        files = sorted((AUCTIONS_DIR / h).glob("*.parquet"))
        if not files:
            print(f"  no files for {h}")
            continue
        df_all = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
        # ensure new cols exist
        for c in ["gamma_resolution_source", "gamma_winning_bucket"]:
            if c not in df_all.columns:
                df_all[c] = ""
        # find candidates to backfill: anything not already 'resolved_yes' from raw data
        targets = df_all[~df_all["resolution_status"].isin(["resolved_yes"])].copy()
        print(f"  total auctions: {len(df_all)}")
        print(f"  candidates (not raw resolved_yes): {len(targets)}")

        n_resolved_new = 0
        n_no_event = 0
        n_not_closed = 0
        n_no_winner = 0
        for idx, row in targets.iterrows():
            slug = row["auction_slug"]
            ev = fetch_event(slug)
            winner, status = find_yes_winner(ev)
            time.sleep(RATE_LIMIT_SEC)

            df_all.at[idx, "gamma_winning_bucket"] = winner
            if status == "resolved_yes":
                df_all.at[idx, "gamma_resolution_source"] = "gamma_events_slug"
                # if existing winning_bucket disagreed or was empty, upgrade
                if not row["winning_bucket"] or normalize_bucket(row["winning_bucket"]) != normalize_bucket(winner):
                    df_all.at[idx, "winning_bucket"] = winner
                df_all.at[idx, "resolution_status"] = "resolved_yes_gamma"
                df_all.at[idx, "confidence"] = "high"
                n_resolved_new += 1
            elif status == "no_event":
                df_all.at[idx, "gamma_resolution_source"] = "no_gamma_event"
                n_no_event += 1
            elif status == "event_not_closed":
                df_all.at[idx, "gamma_resolution_source"] = "event_not_closed"
                n_not_closed += 1
            else:
                df_all.at[idx, "gamma_resolution_source"] = status
                n_no_winner += 1
        print(f"  newly resolved via Gamma: {n_resolved_new}")
        print(f"  no event in Gamma:        {n_no_event}")
        print(f"  event still open:         {n_not_closed}")
        print(f"  closed but no YES winner: {n_no_winner}")

        # mark non-target rows
        for idx, row in df_all.iterrows():
            if row["resolution_status"] == "resolved_yes" and not row["gamma_resolution_source"]:
                df_all.at[idx, "gamma_resolution_source"] = "pre_existing"

        # re-partition write
        # clean old
        for p in (AUCTIONS_DIR / h).glob("*.parquet"):
            p.unlink()
        df_all["start_utc"] = pd.to_datetime(df_all["start_utc"], utc=True)
        df_all["_part"] = df_all["start_utc"].dt.strftime("%Y-%m")
        for part, sub in df_all.groupby("_part"):
            out = AUCTIONS_DIR / h / f"{part}.parquet"
            out.parent.mkdir(parents=True, exist_ok=True)
            sub.drop(columns=["_part"]).to_parquet(out, index=False)
        print(f"  wrote {len(df_all)} rows across {df_all['_part'].nunique()} partitions")

        # new confidence breakdown
        print(f"  NEW confidence breakdown: {df_all['confidence'].value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
