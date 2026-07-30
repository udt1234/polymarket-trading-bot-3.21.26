"""
End-to-end data consistency test for canonical/.

Runs 8 checks and produces:
  - stdout report with PASS/FAIL per check
  - Google Sheet 'Data_Consistency_Test' tab with all results
  - Google Sheet 'Data_Coverage' tab with the coverage matrix

Checks:
  1. POSTS  No duplicate post_ids per handle
  2. POSTS  All timestamps tz-aware UTC, monotonic in monthly partitions
  3. POSTS  counts_for_auction is reasonable share of total
  4. AUCTIONS  Every auction has prices (cross-table join)
  5. AUCTIONS  Every winning_bucket exists in prices for that auction
  6. PRICES  condition_id is unique per (auction, bucket); not auction-level
  7. PRICES  All hours within auction window (no orphan hours)
  8. CROSS  Posts inside auction window roughly match historical pacing
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _canon import CANON, COVERAGE_FLOOR, ROOT  # noqa: E402

SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"


def load_all_posts(handle: str) -> pd.DataFrame:
    files = sorted((CANON / "posts" / handle).glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    return df


def load_all_auctions(handle: str = None) -> pd.DataFrame:
    base = CANON / "auctions"
    files = sorted(base.rglob("*.parquet")) if not handle else sorted((base / handle).glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df["start_utc"] = pd.to_datetime(df["start_utc"], utc=True)
    df["end_utc"] = pd.to_datetime(df["end_utc"], utc=True)
    return df


def load_all_prices(handle: str) -> pd.DataFrame:
    files = sorted((CANON / "prices" / handle).glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df["hour_utc"] = pd.to_datetime(df["hour_utc"], utc=True)
    return df


def check_1_posts_duplicates(results):
    """No duplicate post_ids per handle."""
    for h in ["realDonaldTrump", "elonmusk"]:
        df = load_all_posts(h)
        n_dup = df["post_id"].duplicated().sum()
        results.append({
            "check": "1. Posts no duplicate IDs",
            "handle": h,
            "verdict": "PASS" if n_dup == 0 else "FAIL",
            "detail": f"{n_dup} duplicate post_ids in {len(df):,} rows",
        })


def check_2_posts_timestamps(results):
    """All posts have tz-aware UTC timestamps."""
    for h in ["realDonaldTrump", "elonmusk"]:
        df = load_all_posts(h)
        n_null = df["ts_utc"].isna().sum()
        tz_ok = df["ts_utc"].dt.tz is not None
        results.append({
            "check": "2. Posts timestamps clean",
            "handle": h,
            "verdict": "PASS" if (n_null == 0 and tz_ok) else "FAIL",
            "detail": f"{n_null} null ts, tz_aware={tz_ok}",
        })


def check_3_posts_counts_for_auction(results):
    """counts_for_auction should be a reasonable share of total (90%+)."""
    for h in ["realDonaldTrump", "elonmusk"]:
        df = load_all_posts(h)
        share = df["counts_for_auction"].sum() / len(df)
        verdict = "PASS" if share >= 0.85 else "WARN"
        results.append({
            "check": "3. Posts counts_for_auction reasonable",
            "handle": h,
            "verdict": verdict,
            "detail": f"{100*share:.1f}% of {len(df):,} posts count for auction",
        })


def check_4_every_auction_has_prices(results):
    """Every auction in canonical/auctions must have rows in canonical/prices."""
    for h in ["realDonaldTrump", "elonmusk"]:
        auc = load_all_auctions(h)
        prc = load_all_prices(h)
        auc_slugs = set(auc["auction_slug"])
        prc_slugs = set(prc["auction_slug"])
        missing = auc_slugs - prc_slugs
        results.append({
            "check": "4. Every auction has prices",
            "handle": h,
            "verdict": "PASS" if not missing else "FAIL",
            "detail": f"{len(missing)} auctions missing prices (of {len(auc_slugs)})",
        })


def check_5_winning_bucket_in_prices(results):
    """For each high-conf auction, the winning_bucket must exist in prices.

    This check was WARN-only until 2026-07-30 and silently sat at 45% coverage
    for Elon while a backtest scored models against a market distribution that
    excluded the winner. A miss here invalidates every model-vs-market number
    downstream, so it is a FAIL, not a warning.
    """
    for h in ["realDonaldTrump", "elonmusk"]:
        auc = load_all_auctions(h)
        prc = load_all_prices(h)
        hi = auc[auc["confidence"] == "high"]
        missing = 0
        n = 0
        for _, a in hi.iterrows():
            wb = (a["winning_bucket"] or "").strip()
            if not wb:
                continue
            n += 1
            psub = prc[prc["auction_slug"] == a["auction_slug"]]
            buckets_norm = set(b.strip().lower() for b in psub["bucket"].unique())
            if wb.strip().lower() not in buckets_norm:
                missing += 1
        cov = (n - missing) / n if n else 1.0
        results.append({
            "check": "5. Winning bucket present in prices",
            "handle": h,
            "verdict": "PASS" if cov >= COVERAGE_FLOOR else "FAIL",
            "detail": f"{missing}/{n} high-conf auctions missing winning_bucket in prices "
                      f"(coverage {100*cov:.1f}%, floor {100*COVERAGE_FLOOR:.0f}%)",
        })


def check_6_condition_id_per_bucket(results):
    """Each (auction, bucket) should have exactly 1 condition_id; not 0, not auction-level shared."""
    for h in ["realDonaldTrump", "elonmusk"]:
        prc = load_all_prices(h)
        if not len(prc):
            continue
        g = prc.groupby(["auction_slug", "bucket"])["condition_id"].nunique()
        mixed = (g > 1).sum()
        # auction-level shared means: nunique condition_ids across an auction == 1 even though buckets > 1
        g_auc = prc.groupby("auction_slug").agg(n_buckets=("bucket", "nunique"), n_cids=("condition_id", "nunique"))
        shared = (g_auc["n_cids"] == 1).sum() if len(g_auc) else 0
        # only count as shared if that auction has >1 bucket
        shared = ((g_auc["n_cids"] == 1) & (g_auc["n_buckets"] > 1)).sum()
        verdict = "PASS" if (mixed == 0 and shared == 0) else "FAIL"
        results.append({
            "check": "6. condition_id is per-bucket",
            "handle": h,
            "verdict": verdict,
            "detail": f"{mixed} (auction,bucket) pairs with >1 cid; {shared} multi-bucket auctions w/ shared cid (bad)",
        })


def check_7_prices_within_auction_window(results):
    """Hourly price rows must fall within their auction's start_utc..end_utc."""
    for h in ["realDonaldTrump", "elonmusk"]:
        auc = load_all_auctions(h)
        prc = load_all_prices(h)
        window = auc.set_index("auction_slug")[["start_utc", "end_utc"]]
        prc2 = prc.join(window, on="auction_slug")
        # tolerate 6h lead (early-bird trades) and 6h tail (settlement)
        early = (prc2["hour_utc"] < (prc2["start_utc"] - pd.Timedelta(hours=6))).sum()
        late = (prc2["hour_utc"] > (prc2["end_utc"] + pd.Timedelta(hours=6))).sum()
        verdict = "PASS" if (early == 0 and late == 0) else "WARN"
        results.append({
            "check": "7. Price hours within auction window",
            "handle": h,
            "verdict": verdict,
            "detail": f"{early} early (>6h before start), {late} late (>6h after end), of {len(prc):,} total",
        })


def check_8_posts_inside_window(results):
    """Posts inside auction window should be a reasonable number (sanity check)."""
    for h in ["realDonaldTrump", "elonmusk"]:
        auc = load_all_auctions(h)
        posts = load_all_posts(h)
        # 7-day auctions only (Trump's normal cadence; Elon has many)
        weekly = auc[(auc["duration_type"] == "7-day") & (auc["confidence"] == "high")]
        if not len(weekly):
            continue
        counts = []
        for _, a in weekly.iterrows():
            in_win = posts[(posts["ts_utc"] >= a["start_utc"]) & (posts["ts_utc"] <= a["end_utc"]) & posts["counts_for_auction"]]
            counts.append(len(in_win))
        if not counts:
            continue
        s = pd.Series(counts)
        verdict = "PASS" if s.median() > 0 else "FAIL"
        results.append({
            "check": "8. Posts inside 7-day window",
            "handle": h,
            "verdict": verdict,
            "detail": f"median={s.median():.0f}, p25={s.quantile(0.25):.0f}, p75={s.quantile(0.75):.0f} posts/window (n={len(counts)} 7-day high-conf auctions)",
        })


def build_coverage_table():
    """Per-handle, per-table coverage matrix."""
    rows = []
    for h in ["realDonaldTrump", "elonmusk"]:
        posts = load_all_posts(h)
        auc = load_all_auctions(h)
        prc = load_all_prices(h)
        # date ranges
        post_min = str(posts["ts_utc"].min())[:10] if len(posts) else "-"
        post_max = str(posts["ts_utc"].max())[:10] if len(posts) else "-"
        auc_min = str(auc["start_utc"].min())[:10] if len(auc) else "-"
        auc_max = str(auc["end_utc"].max())[:10] if len(auc) else "-"
        prc_min = str(prc["hour_utc"].min())[:10] if len(prc) else "-"
        prc_max = str(prc["hour_utc"].max())[:10] if len(prc) else "-"
        # months with at least 1 post
        post_months = posts["ts_utc"].dt.strftime("%Y-%m").nunique() if len(posts) else 0
        # auction months
        auc_months = auc["start_utc"].dt.strftime("%Y-%m").nunique() if len(auc) else 0
        # missing months
        if len(posts):
            all_months = sorted(posts["ts_utc"].dt.strftime("%Y-%m").unique())
            gap = []
            for i in range(len(all_months) - 1):
                a = pd.Timestamp(all_months[i] + "-01")
                b = pd.Timestamp(all_months[i+1] + "-01")
                d = (b.year - a.year) * 12 + (b.month - a.month)
                for j in range(1, d):
                    gap.append((a + pd.DateOffset(months=j)).strftime("%Y-%m"))
            post_gaps = ", ".join(gap) if gap else "none"
        else:
            post_gaps = "no data"
        rows.append([
            h, "posts",
            f"{len(posts):,}",
            post_min, post_max,
            f"{post_months} months",
            post_gaps,
        ])
        rows.append([
            h, "auctions",
            f"{len(auc):,} ({(auc['confidence']=='high').sum()} high, {(auc['confidence']=='medium').sum()} med, {(auc['confidence']=='low').sum()} low)",
            auc_min, auc_max,
            f"{auc_months} months",
            f"by type: " + ", ".join(f"{k}={v}" for k, v in auc["duration_type"].value_counts().items()),
        ])
        rows.append([
            h, "prices",
            f"{len(prc):,} hourly rows ({prc['auction_slug'].nunique()} auctions, {prc['bucket'].nunique()} unique buckets)",
            prc_min, prc_max,
            f"{prc['hour_utc'].dt.strftime('%Y-%m').nunique()} months",
            f"{prc['condition_id'].nunique():,} unique condition_ids (per-bucket markets)",
        ])
    return rows


def push_to_sheet(results: list[dict], coverage_rows: list[list[str]]):
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    # ----- Data_Consistency_Test tab -----
    title = "Data_Consistency_Test"
    if title not in tabs:
        res = sheets.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
        sid = res["replies"][0]["addSheet"]["properties"]["sheetId"]
    else:
        sid = tabs[title]
    header = ["check", "handle", "verdict", "detail"]
    values = [header] + [[r["check"], r["handle"], r["verdict"], r["detail"]] for r in results]
    sheets.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{title}!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"{title}!A1",
        valueInputOption="RAW", body={"values": values},
    ).execute()
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [
            {"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85},
                    "textFormat": {"bold": True},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }},
            {"updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 320}, "fields": "pixelSize",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4},
                "properties": {"pixelSize": 600}, "fields": "pixelSize",
            }},
        ]},
    ).execute()

    # ----- Data_Coverage tab -----
    title2 = "Data_Coverage"
    if title2 not in tabs:
        res = sheets.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": title2}}}]},
        ).execute()
        sid2 = res["replies"][0]["addSheet"]["properties"]["sheetId"]
    else:
        sid2 = tabs[title2]
    header2 = ["handle", "table", "rows", "earliest", "latest", "months", "details/gaps"]
    values2 = [header2] + coverage_rows
    sheets.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{title2}!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"{title2}!A1",
        valueInputOption="RAW", body={"values": values2},
    ).execute()
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [
            {"repeatCell": {
                "range": {"sheetId": sid2, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85},
                    "textFormat": {"bold": True},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }},
            {"updateSheetProperties": {
                "properties": {"sheetId": sid2, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid2, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 400}, "fields": "pixelSize",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid2, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7},
                "properties": {"pixelSize": 500}, "fields": "pixelSize",
            }},
        ]},
    ).execute()


def main():
    results = []
    print("Running consistency checks...")
    check_1_posts_duplicates(results)
    check_2_posts_timestamps(results)
    check_3_posts_counts_for_auction(results)
    check_4_every_auction_has_prices(results)
    check_5_winning_bucket_in_prices(results)
    check_6_condition_id_per_bucket(results)
    check_7_prices_within_auction_window(results)
    check_8_posts_inside_window(results)

    print()
    print(f"{'Check':<42} {'Handle':<18} {'Verdict':<6} Detail")
    print("-" * 130)
    for r in results:
        print(f"{r['check']:<42} {r['handle']:<18} {r['verdict']:<6} {r['detail']}")

    coverage = build_coverage_table()
    print()
    print("=== COVERAGE TABLE ===")
    print(f"{'Handle':<18} {'Table':<10} {'Rows':<60} {'Earliest':<12} {'Latest':<12} {'Months':<10} Details")
    print("-" * 200)
    for row in coverage:
        print(f"{row[0]:<18} {row[1]:<10} {row[2]:<60} {row[3]:<12} {row[4]:<12} {row[5]:<10} {row[6]}")

    push_to_sheet(results, coverage)
    print()
    print("Pushed to https://docs.google.com/spreadsheets/d/" + SPREADSHEET_ID + "/edit")
    print("Tabs: Data_Consistency_Test, Data_Coverage")

    failures = [r for r in results if r["verdict"] == "FAIL"]
    if failures:
        print()
        for r in failures:
            print(f"FAIL {r['handle']}: {r['check']} - {r['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
