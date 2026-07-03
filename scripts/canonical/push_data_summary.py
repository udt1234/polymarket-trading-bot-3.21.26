"""
Push a Data_Summary tab to the canonical sheet with EXACT counts of what we have.

Sections:
  POSTS - per handle, per source, per type
  AUCTIONS - per handle, per duration, per confidence
  PRICES - per handle, hourly rows + unique markets + date range
  COVERAGE GAPS - the known holes
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"
TITLE = "Data_Summary"


def load_all(table: str, handle: str = None) -> pd.DataFrame:
    base = CANON / table
    if handle:
        files = sorted((base / handle).glob("*.parquet"))
    else:
        files = sorted(base.rglob("*.parquet"))
    if not files: return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)


def fmt_date(ts):
    if pd.isna(ts): return "-"
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def fmt_n(n):
    if n == 0 or n is None: return "0"
    return f"{int(n):,}"


def build_summary():
    rows = []

    # ===== POSTS =====
    rows.append(["═══ POSTS ═══"])
    rows.append(["handle", "metric", "value", "notes"])
    for handle in ["realDonaldTrump", "elonmusk"]:
        df = load_all("posts", handle)
        if not len(df): continue
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
        rows.append([handle, "total rows", fmt_n(len(df)), ""])
        rows.append([handle, "date range", f"{fmt_date(df['ts_utc'].min())} → {fmt_date(df['ts_utc'].max())}", ""])
        rows.append([handle, "months covered", fmt_n(df['ts_utc'].dt.strftime('%Y-%m').nunique()), ""])
        # by source
        rows.append([handle, "── by source ──", "", ""])
        for src, n in df["source"].value_counts().items():
            rows.append([handle, f"  source={src}", fmt_n(n), f"{100*n/len(df):.1f}%"])
        # by type
        rows.append([handle, "── by type ──", "", ""])
        rows.append([handle, "  main feed posts (none of below)", fmt_n((~df['is_reply'] & ~df['is_repost'] & ~df['is_quote'] & ~df['is_community_repost']).sum()), ""])
        rows.append([handle, "  reposts (RT)", fmt_n(df['is_repost'].sum()), "counts toward auction (Polymarket rule)"])
        rows.append([handle, "  quote posts", fmt_n(df['is_quote'].sum()), "counts toward auction"])
        rows.append([handle, "  replies", fmt_n(df['is_reply'].sum()), "does NOT count toward auction (Polymarket rule)"])
        rows.append([handle, "  community reposts", fmt_n(df['is_community_repost'].sum()), "does NOT count (Elon-specific)"])
        # counts_for_auction final
        rows.append([handle, "counts_for_auction = True", fmt_n(df['counts_for_auction'].sum()),
                     f"{100*df['counts_for_auction'].sum()/len(df):.1f}% of total"])
        rows.append(["", "", "", ""])

    # ===== AUCTIONS =====
    rows.append([""])
    rows.append(["═══ AUCTIONS ═══"])
    rows.append(["handle", "metric", "value", "notes"])
    for handle in ["realDonaldTrump", "elonmusk"]:
        df = load_all("auctions", handle)
        if not len(df): continue
        df["start_utc"] = pd.to_datetime(df["start_utc"], utc=True)
        df["end_utc"] = pd.to_datetime(df["end_utc"], utc=True)
        rows.append([handle, "total auctions", fmt_n(len(df)), ""])
        rows.append([handle, "date range (start_utc → end_utc)", f"{fmt_date(df['start_utc'].min())} → {fmt_date(df['end_utc'].max())}", ""])
        rows.append([handle, "── by duration_type ──", "", ""])
        for dt, n in df["duration_type"].value_counts().items():
            rows.append([handle, f"  {dt}", fmt_n(n), ""])
        rows.append([handle, "── by confidence ──", "", ""])
        for c, n in df["confidence"].value_counts().items():
            rows.append([handle, f"  {c}", fmt_n(n), ""])
        rows.append([handle, "── by resolution_status ──", "", ""])
        for s, n in df["resolution_status"].value_counts().items():
            rows.append([handle, f"  {s}", fmt_n(n), ""])
        # backtest-usable
        usable = df[df["confidence"].isin(["high", "medium"])]
        rows.append([handle, "BACKTEST-USABLE (conf high+medium)", fmt_n(len(usable)),
                     f"{100*len(usable)/len(df):.1f}% of total"])
        rows.append(["", "", "", ""])

    # ===== PRICES =====
    rows.append([""])
    rows.append(["═══ PRICES ═══"])
    rows.append(["handle", "metric", "value", "notes"])
    for handle in ["realDonaldTrump", "elonmusk"]:
        df = load_all("prices", handle)
        if not len(df): continue
        df["hour_utc"] = pd.to_datetime(df["hour_utc"], utc=True)
        rows.append([handle, "hourly OHLC rows", fmt_n(len(df)), ""])
        rows.append([handle, "unique auctions covered", fmt_n(df['auction_slug'].nunique()), ""])
        rows.append([handle, "unique per-bucket markets (condition_ids)", fmt_n(df['condition_id'].nunique()), ""])
        rows.append([handle, "unique bucket labels", fmt_n(df['bucket'].nunique()), ""])
        rows.append([handle, "date range UTC", f"{fmt_date(df['hour_utc'].min())} → {fmt_date(df['hour_utc'].max())}", ""])
        rows.append([handle, "total trade volume (USD)", f"${df['vol_usd'].sum():,.0f}", ""])
        rows.append([handle, "total trades", fmt_n(df['n_trades'].sum()), ""])
        rows.append(["", "", "", ""])

    # ===== KNOWN GAPS / CAVEATS =====
    rows.append([""])
    rows.append(["═══ KNOWN GAPS / CAVEATS ═══"])
    rows.append(["item", "status", "details", ""])
    # Find canonical post date range vs auction date range for elonmusk
    eposts = load_all("posts", "elonmusk")
    eauc = load_all("auctions", "elonmusk")
    if len(eposts) and len(eauc):
        eposts["ts_utc"] = pd.to_datetime(eposts["ts_utc"], utc=True)
        eauc["start_utc"] = pd.to_datetime(eauc["start_utc"], utc=True)
        post_start = eposts["ts_utc"].min()
        auc_start = eauc["start_utc"].min()
        gap_auctions = eauc[eauc["start_utc"] < post_start]
        rows.append(["Elon post-auction overlap",
                     "PARTIAL" if len(gap_auctions) else "FULL",
                     f"posts start {fmt_date(post_start)}, auctions start {fmt_date(auc_start)}; "
                     f"{len(gap_auctions)} auctions before post coverage", ""])
    # Demoted (low-conf) auctions
    for h in ["realDonaldTrump", "elonmusk"]:
        df = load_all("auctions", h)
        if len(df):
            low = (df["confidence"] == "low").sum()
            rows.append([f"{h} low-conf auctions", "EXCLUDED FROM BACKTESTS", fmt_n(low),
                        "Either unresolved, ambiguous, or bracket structure incomplete"])

    rows.append([""])
    rows.append(["Generated by scripts/canonical/push_data_summary.py", "", "", ""])
    return rows


def main():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    rows = build_summary()
    print(f"[summary] built {len(rows)} rows")

    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    if TITLE in tabs:
        sid = tabs[TITLE]
    else:
        res = sheets.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": TITLE}}}]},
        ).execute()
        sid = res["replies"][0]["addSheet"]["properties"]["sheetId"]

    # normalize to consistent width
    width = max(len(r) for r in rows)
    norm = [[str(c) if c is not None else "" for c in r] + [""] * (width - len(r)) for r in rows]

    sheets.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{TITLE}!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"{TITLE}!A1",
        valueInputOption="RAW", body={"values": norm},
    ).execute()

    # Format: highlight section headers (rows starting with ═══)
    section_rows = [i for i, r in enumerate(rows) if r and str(r[0]).startswith("═══")]
    requests = [
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 280}, "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 360}, "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": 200}, "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4},
            "properties": {"pixelSize": 400}, "fields": "pixelSize",
        }},
    ]
    for r in section_rows:
        requests.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r+1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                "textFormat": {"foregroundColor": {"red": 1, "green": 0.85, "blue": 0.4}, "bold": True, "fontSize": 12},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }})
    sheets.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": requests}).execute()

    print(f"\nDone: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit (tab: {TITLE})")


if __name__ == "__main__":
    main()
