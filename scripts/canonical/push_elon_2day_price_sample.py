"""Push a 2-day Elon auction sample to Elon_Prices (replaces the 7-day sample).

Picks the LARGEST 2-day Elon auction (most trades) for richer sample.
"""
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
import time

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
RAW = CANON / "_raw_imports" / "api_trades_v2"
SS = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA = Path.home() / ".claude" / "google-service-account.json"
ET = ZoneInfo("America/New_York")

TARGET_SLUG = "elon-musk-of-tweets-january-10-january-12"  # biggest 2-day, high-conf
BANNER = f"ℹ Sample of every trade for a 2-day Elon auction ({TARGET_SLUG}). Columns: auction_slug, auction_title, duration_type, bucket, price, side, hours_in, etc."
HEADER = ["auction_slug","auction_title","duration_type","ts_et","ts_utc","hours_in","side","outcome","bucket","is_winning_bucket","bracket_market_title","price","size_shares","notional_usd","trader_name","trader_wallet","tx_hash"]


def winning_bucket(df):
    if "_outcome_resolved" not in df.columns:
        return ""
    import json
    for b, g in df.groupby("_bucket"):
        o = g["_outcome_resolved"].dropna()
        if not len(o): continue
        try:
            parsed = json.loads(o.iloc[-1]) if isinstance(o.iloc[-1], str) else o.iloc[-1]
            if parsed == ["1","0"] or parsed == [1,0]: return str(b)
        except: continue
    return ""


def main():
    # Load raw trades for the 2-day auction
    raw_path = RAW / f"{TARGET_SLUG}.parquet"
    if not raw_path.exists():
        print(f"ERR: {raw_path} not found"); return
    df = pd.read_parquet(raw_path)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts")
    print(f"Loaded {len(df):,} trades for {TARGET_SLUG}")

    wb = winning_bucket(df)
    print(f"Winning bucket: {wb}")

    # Lookup canonical meta (title + duration_type)
    auc_path = next((CANON/"auctions/elonmusk").glob("*.parquet"), None)
    titles_meta = {}
    for p in (CANON/"auctions/elonmusk").glob("*.parquet"):
        a = pd.read_parquet(p, columns=["auction_slug","title","duration_type"])
        for _, r in a.iterrows():
            titles_meta[str(r["auction_slug"])] = (str(r["title"]), str(r["duration_type"]))
    auction_title, auction_duration = titles_meta.get(TARGET_SLUG, ("",""))
    print(f"Title: {auction_title}")
    print(f"Duration: {auction_duration}")

    # Sample 500 evenly-spaced trades
    if len(df) > 500:
        idx = list(range(0, len(df), max(1, len(df) // 500)))[:500]
        df = df.iloc[idx]

    rows = [HEADER]
    for _, r in df.iterrows():
        ts = r["ts"]
        ts_et = ts.tz_convert(ET) if pd.notna(ts) else None
        bucket = str(r.get("_bucket",""))
        rows.append([
            TARGET_SLUG,
            auction_title,
            auction_duration,
            ts_et.strftime("%Y-%m-%d %H:%M:%S ET") if ts_et else "",
            ts.strftime("%Y-%m-%d %H:%M:%S UTC") if pd.notna(ts) else "",
            f"{r.get('hours_in',0):.2f}",
            str(r.get("side","")),
            str(r.get("outcome","")),
            bucket,
            "YES" if (wb and bucket==wb) else "",
            str(r.get("title","")),
            f"{r.get('price',0):.4f}",
            f"{r.get('size',0):.2f}",
            f"{r.get('notional',0):.2f}",
            str(r.get("name",""))[:30],
            str(r.get("proxyWallet",""))[:20]+"...",
            str(r.get("transactionHash",""))[:20]+"...",
        ])

    # Push
    creds = service_account.Credentials.from_service_account_file(
        str(SA), scopes=["https://www.googleapis.com/auth/spreadsheets"], subject="darwin@xagency.com",
    )
    sheets = build("sheets","v4",credentials=creds,cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=SS).execute()
    sid = next(s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"]=="Elon_Prices")

    # 1. Unmerge row 1
    try:
        sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": [
            {"unmergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 3, "startColumnIndex": 0, "endColumnIndex": 26}}}
        ]}).execute()
    except: pass
    # 2. Clear sheet
    sheets.spreadsheets().values().clear(spreadsheetId=SS, range="Elon_Prices!A:Z").execute()
    # 3. Write banner + header + data
    full_rows = [[BANNER]] + rows  # row 1 = banner, row 2 = header, row 3+ = data
    sheets.spreadsheets().values().update(spreadsheetId=SS, range="Elon_Prices!A1", valueInputOption="RAW", body={"values": full_rows}).execute()
    # 4. Re-format
    sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": [
        {"mergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 26}, "mergeType": "MERGE_ALL"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1}, "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1}, "textFormat": {"fontFamily": "Calibri", "foregroundColor": {"red": 0, "green": 0, "blue": 0}, "bold": True, "fontSize": 11}, "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 36}, "fields": "pixelSize"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 2}}, "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2}, "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93}, "textFormat": {"fontFamily": "Calibri", "bold": True, "fontSize": 10, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}, "wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 2}, "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1}, "textFormat": {"fontFamily": "Calibri", "bold": False, "fontSize": 10, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}, "wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)"}},
    ]}).execute()
    print(f"\nPushed {len(rows)-1} trades to Elon_Prices")
    print(f"https://docs.google.com/spreadsheets/d/{SS}/edit")


if __name__ == "__main__":
    main()
