"""Push canonical/posts_history/elonmusk samples to the canonical sheet.

Creates/refreshes:
  Posts_History — 30 random rows per era (pre_acquisition, transition, current_x)
                          + 10 boundary rows around each era transition
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
TITLE = "Posts_History"

ELON_ACQUISITION = pd.Timestamp("2022-10-27", tz="UTC")
ELON_X_REBRAND = pd.Timestamp("2023-07-23", tz="UTC")


def main():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    files = sorted((CANON / "posts_history" / "elonmusk").glob("*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df = df.sort_values("ts_utc").reset_index(drop=True)
    print(f"Loaded {len(df):,} posts_history rows")

    # --- Headline summary block ---
    summary = []
    summary.append(["POSTS_HISTORY ELON MUSK — 5yr ML training data"])
    summary.append([])
    summary.append(["era", "rows", "date range", "%"])
    for era, sub in df.groupby("era"):
        summary.append([era, f"{len(sub):,}",
                        f"{sub['ts_utc'].min().date()} → {sub['ts_utc'].max().date()}",
                        f"{100*len(sub)/len(df):.1f}%"])
    summary.append([])

    # --- Sample 30 random per era ---
    rows = list(summary)
    rows.append(["── 30 RANDOM PER ERA ──"])
    rows.append(["era", "ts_utc", "ts_et", "post_id", "is_reply", "is_repost", "is_quote",
                 "counts_for_auction", "source", "content_text", "url"])
    for era in ["pre_acquisition", "transition", "current_x"]:
        sub = df[df["era"] == era]
        sample = sub.sample(min(30, len(sub)), random_state=42).sort_values("ts_utc")
        for _, r in sample.iterrows():
            rows.append([
                era,
                str(r["ts_utc"])[:19],
                str(r["ts_et"])[:19],
                str(r["post_id"]),
                str(bool(r["is_reply"])),
                str(bool(r["is_repost"])),
                str(bool(r["is_quote"])),
                str(bool(r["counts_for_auction"])),
                str(r["source"]),
                str(r["content_text"])[:200],
                str(r["url"]),
            ])

    # --- Boundary rows around each era transition (5 before, 5 after) ---
    rows.append([])
    rows.append(["── ERA BOUNDARY CHECKS ──"])
    rows.append(["era", "ts_utc", "ts_et", "post_id", "is_reply", "is_repost", "is_quote",
                 "counts_for_auction", "source", "content_text", "url"])

    # Boundary 1: pre_acquisition → transition (Oct 27 2022)
    rows.append(["─ Boundary 1: pre_acquisition → transition (Oct 27 2022) ─"])
    before = df[(df["ts_utc"] < ELON_ACQUISITION)].tail(5)
    after = df[(df["ts_utc"] >= ELON_ACQUISITION)].head(5)
    for _, r in pd.concat([before, after]).iterrows():
        rows.append([
            r["era"], str(r["ts_utc"])[:19], str(r["ts_et"])[:19], str(r["post_id"]),
            str(bool(r["is_reply"])), str(bool(r["is_repost"])), str(bool(r["is_quote"])),
            str(bool(r["counts_for_auction"])), str(r["source"]),
            str(r["content_text"])[:200], str(r["url"]),
        ])

    rows.append([])
    # Boundary 2: transition → current_x (Jul 23 2023)
    rows.append(["─ Boundary 2: transition → current_x (Jul 23 2023) ─"])
    before = df[(df["ts_utc"] < ELON_X_REBRAND) & (df["ts_utc"] >= ELON_ACQUISITION)].tail(5)
    after = df[(df["ts_utc"] >= ELON_X_REBRAND)].head(5)
    for _, r in pd.concat([before, after]).iterrows():
        rows.append([
            r["era"], str(r["ts_utc"])[:19], str(r["ts_et"])[:19], str(r["post_id"]),
            str(bool(r["is_reply"])), str(bool(r["is_repost"])), str(bool(r["is_quote"])),
            str(bool(r["counts_for_auction"])), str(r["source"]),
            str(r["content_text"])[:200], str(r["url"]),
        ])

    # --- Push to sheet ---
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

    width = max(len(r) for r in rows)
    norm = [[str(c) if c is not None else "" for c in r] + [""] * (width - len(r)) for r in rows]

    sheets.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{TITLE}!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"{TITLE}!A1",
        valueInputOption="RAW", body={"values": norm},
    ).execute()

    # Format: bold section headers + widen content column
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 9, "endIndex": 10},
                "properties": {"pixelSize": 480}, "fields": "pixelSize",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 10, "endIndex": 11},
                "properties": {"pixelSize": 280}, "fields": "pixelSize",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 130}, "fields": "pixelSize",
            }},
        ]},
    ).execute()

    n_data_rows = sum(1 for r in rows if r and len(r) > 5 and r[0] in ("pre_acquisition", "transition", "current_x"))
    print(f"Wrote {n_data_rows} data sample rows to {TITLE}")
    print(f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")


if __name__ == "__main__":
    main()
