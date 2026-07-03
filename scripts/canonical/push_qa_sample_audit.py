"""
Push a 'QA_Audit' tab to the canonical sheet.

For each canonical table (auctions, prices, posts), samples N rows and
shows side-by-side:
  - the canonical value
  - the ground-truth value (Gamma for auctions, raw whale parquet for prices,
    structural check for posts)
  - PASS/FAIL verdict
  - any diff detail

So Sir can spot-check exactly what the QA gate is comparing.
"""
from __future__ import annotations

import json
import random
import sys
import urllib.request
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
RAW_TRADES = CANON / "_raw_imports" / "api_trades_v2"
GAMMA_CACHE = CANON / "_gamma_cache"

SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"
SUBJECT = "darwin@xagency.com"

SAMPLE_AUCTIONS = 20
SAMPLE_PRICES = 20
SAMPLE_POSTS = 20

random.seed(42)


def gamma_event(slug: str):
    cache = GAMMA_CACHE / f"{slug}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except Exception:
            pass
    try:
        req = urllib.request.Request(
            f"https://gamma-api.polymarket.com/events?slug={slug}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        GAMMA_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
        return data
    except Exception:
        return None


def audit_auctions():
    parts = sorted((CANON / "auctions").rglob("*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df = df[df["confidence"].isin(["high", "medium"])].reset_index(drop=True)
    sample = df.sample(min(SAMPLE_AUCTIONS, len(df)), random_state=42)
    rows = [["TABLE: AUCTIONS — sample 20 random high/medium confidence auctions, verify winning_bucket against live Gamma"]]
    rows.append([])
    rows.append([
        "handle", "auction_slug", "canonical_winning_bucket", "gamma_winning_bucket",
        "verdict", "diff_notes", "duration_type", "confidence", "resolution_status",
    ])
    for _, r in sample.iterrows():
        slug = r["auction_slug"]
        canon = (r["winning_bucket"] or "").strip()
        ev = gamma_event(slug)
        gamma_w = ""
        if ev and isinstance(ev, list) and len(ev):
            for m in ev[0].get("markets", []):
                op = m.get("outcomePrices", "[]")
                try:
                    op = json.loads(op) if isinstance(op, str) else op
                except Exception:
                    op = []
                if op == ["1", "0"] or op == [1, 0]:
                    gamma_w = (m.get("groupItemTitle") or "").strip()
                    break
        # normalize
        c_norm = canon.replace("–", "-").replace("—", "-").lower()
        g_norm = gamma_w.replace("–", "-").replace("—", "-").lower()
        if c_norm == g_norm and c_norm:
            verdict = "PASS"
            note = ""
        elif not g_norm and not c_norm:
            verdict = "PASS (both empty — unresolved)"
            note = ""
        elif not g_norm:
            verdict = "SKIP (gamma no resolution)"
            note = ""
        else:
            verdict = "FAIL"
            note = f"canonical='{canon}' vs gamma='{gamma_w}'"
        rows.append([
            r["handle"], slug, canon, gamma_w, verdict, note,
            r["duration_type"], r["confidence"], r["resolution_status"],
        ])
    return rows


def audit_prices():
    parts = sorted((CANON / "prices").rglob("*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    sample = df.sample(min(SAMPLE_PRICES, len(df)), random_state=42)
    rows = [["TABLE: PRICES — sample 20 random hourly OHLC rows, verify close against raw api_trades_v2 trades"]]
    rows.append([])
    rows.append([
        "handle", "auction_slug", "bucket", "hour_utc",
        "canonical_close", "raw_last_yes_price", "abs_diff", "verdict", "n_raw_trades_in_hour",
    ])
    raw_cache: dict[str, pd.DataFrame] = {}
    for _, r in sample.iterrows():
        slug = r["auction_slug"]
        bucket = r["bucket"]
        ts = pd.Timestamp(r["hour_utc"])
        hour = ts if ts.tzinfo else ts.tz_localize("UTC")
        canon_close = float(r["close"])
        if slug not in raw_cache:
            raw_path = RAW_TRADES / f"{slug}.parquet"
            if not raw_path.exists():
                rows.append([r["handle"], slug, bucket, str(hour), f"{canon_close:.4f}",
                             "", "", "SKIP (no raw)", 0])
                continue
            raw_cache[slug] = pd.read_parquet(raw_path)
        rdf = raw_cache[slug].copy()
        rdf["ts"] = pd.to_datetime(rdf["ts"], utc=True, errors="coerce")
        rsub = rdf[(rdf["_bucket"] == bucket)
                   & (rdf["ts"] >= hour)
                   & (rdf["ts"] < hour + pd.Timedelta(hours=1))].sort_values("ts")
        if len(rsub) == 0:
            rows.append([r["handle"], slug, bucket, str(hour), f"{canon_close:.4f}",
                         "", "", "SKIP (no raw in hour)", 0])
            continue
        last = rsub.iloc[-1]
        yes_price = last["price"] if last["outcome"] == "Yes" else (1.0 - last["price"])
        diff = abs(canon_close - yes_price)
        verdict = "PASS" if diff <= 0.01 else "FAIL"
        rows.append([
            r["handle"], slug, bucket, str(hour),
            f"{canon_close:.4f}", f"{yes_price:.4f}", f"{diff:.4f}", verdict, len(rsub),
        ])
    return rows


def audit_posts():
    rows = [["TABLE: POSTS — sample 20 random posts, verify structural integrity (id, ts, url)"]]
    rows.append([])
    rows.append([
        "handle", "post_id", "ts_utc", "url",
        "content_preview", "counts_for_auction", "source", "verdict",
    ])
    for handle in ["realDonaldTrump", "elonmusk"]:
        parts = sorted((CANON / "posts" / handle).glob("*.parquet"))
        df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
        sample = df.sample(min(SAMPLE_POSTS // 2, len(df)), random_state=42)
        for _, r in sample.iterrows():
            issues = []
            if not r.get("post_id"):
                issues.append("missing post_id")
            if pd.isna(r.get("ts_utc")):
                issues.append("null ts_utc")
            url = r.get("url", "")
            if not (url.startswith("https://") or url.startswith("xtracker://")):
                issues.append(f"bad url: {url[:30]}")
            verdict = "PASS" if not issues else f"FAIL ({'; '.join(issues)})"
            rows.append([
                r["handle"], str(r["post_id"]), str(r["ts_utc"])[:19], url[:80],
                (r.get("content_text", "") or "")[:80],
                str(r.get("counts_for_auction", "")),
                str(r.get("source", "")), verdict,
            ])
    return rows


def main() -> int:
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject=SUBJECT,
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    print("[1/3] auditing AUCTIONS...")
    auc = audit_auctions()
    print(f"  built {len(auc)-3} sample rows")

    print("[2/3] auditing PRICES...")
    prc = audit_prices()
    print(f"  built {len(prc)-3} sample rows")

    print("[3/3] auditing POSTS...")
    pst = audit_posts()
    print(f"  built {len(pst)-3} sample rows")

    # combine into one tab with section dividers
    blank = [[""]]
    all_rows = auc + blank + blank + prc + blank + blank + pst

    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    title = "QA_Audit"
    if title in tabs:
        sid = tabs[title]
    else:
        res = sheets.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
        sid = res["replies"][0]["addSheet"]["properties"]["sheetId"]

    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{title}!A:Z"
    ).execute()
    # pad rows to consistent length
    width = max(len(r) for r in all_rows)
    norm_rows = [[*[str(c) for c in r], *([""] * (width - len(r)))] for r in all_rows]
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{title}!A1",
        valueInputOption="RAW",
        body={"values": norm_rows},
    ).execute()
    # format: bold section headers, freeze nothing, widen col B (slugs)
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 380}, "fields": "pixelSize",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5},
                "properties": {"pixelSize": 200}, "fields": "pixelSize",
            }},
        ]},
    ).execute()
    print(f"\nDone — see https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit (tab: {title})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
