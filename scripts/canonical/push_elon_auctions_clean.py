"""Re-push Elon_Auctions_Inventory with unknown-duration auctions filtered out."""
from pathlib import Path
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
import time

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
SS = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA = Path.home() / ".claude" / "google-service-account.json"

HEADER = ['file','auction_slug','duration_type','window_days','n_trades','n_unique_traders',
          'first_trade_et','last_trade_et','trade_span_hours','unique_buckets','all_buckets',
          'winning_bucket','resolution_status','winner_close_price','winner_open_price',
          'winner_peak_price','winner_low_price','total_volume_usd','title','condition_id']


def main():
    auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/"auctions/elonmusk").glob("*.parquet"))], ignore_index=True)
    print(f"Before filter: {len(auc)} auctions")
    auc = auc[auc["duration_type"] != "unknown"].copy()
    print(f"After filter:  {len(auc)} auctions")
    print(f"Duration breakdown: {auc['duration_type'].value_counts().to_dict()}")

    auc = auc.sort_values(["duration_type", "start_utc"])
    rows = [HEADER]
    for _, r in auc.iterrows():
        rows.append([
            r.get("source_file", ""),
            str(r.get("auction_slug", "")),
            str(r.get("duration_type", "")),
            f"{r.get('window_days', 0):.1f}" if pd.notna(r.get("window_days")) else "",
            str(int(r.get("n_trades", 0))),
            str(int(r.get("n_unique_traders", 0))),
            pd.Timestamp(r["start_et"]).strftime("%Y-%m-%d %H:%M ET") if pd.notna(r.get("start_et")) else "",
            pd.Timestamp(r["end_et"]).strftime("%Y-%m-%d %H:%M ET") if pd.notna(r.get("end_et")) else "",
            f"{(pd.Timestamp(r['end_utc']) - pd.Timestamp(r['start_utc'])).total_seconds()/3600:.1f}",
            str(int(r.get("n_buckets", 0))),
            str(r.get("all_buckets", ""))[:200],
            str(r.get("winning_bucket", "")),
            str(r.get("resolution_status", "")),
            f"{r.get('winner_close_price', 0):.4f}" if pd.notna(r.get("winner_close_price")) else "",
            f"{r.get('winner_open_price', 0):.4f}" if pd.notna(r.get("winner_open_price")) else "",
            f"{r.get('winner_peak_price', 0):.4f}" if pd.notna(r.get("winner_peak_price")) else "",
            f"{r.get('winner_low_price', 0):.4f}" if pd.notna(r.get("winner_low_price")) else "",
            f"{r.get('total_volume_usd', 0):.0f}",
            str(r.get("title", ""))[:200],
            str(r.get("winner_condition_id", ""))[:30] + "..." if r.get("winner_condition_id") else "",
        ])

    BANNER = f"ℹ All {len(auc)} Elon tweet-count auctions (unknown durations excluded) — duration_type, winners, OHLC of winning bracket."

    creds = service_account.Credentials.from_service_account_file(
        str(SA), scopes=["https://www.googleapis.com/auth/spreadsheets"], subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=SS).execute()
    sid = next(s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == "Elon_Auctions_Inventory")

    # Unmerge, clear, write banner + header + data
    try:
        sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": [
            {"unmergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 3,
                                          "startColumnIndex": 0, "endColumnIndex": 26}}},
        ]}).execute()
    except: pass
    time.sleep(1)
    sheets.spreadsheets().values().clear(spreadsheetId=SS, range="Elon_Auctions_Inventory!A:Z").execute()
    time.sleep(1)
    full_rows = [[BANNER]] + rows
    sheets.spreadsheets().values().update(spreadsheetId=SS, range="Elon_Auctions_Inventory!A1",
                                            valueInputOption="RAW", body={"values": full_rows}).execute()
    time.sleep(1)
    sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": [
        {"mergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                                    "startColumnIndex": 0, "endColumnIndex": 26}, "mergeType": "MERGE_ALL"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                          "cell": {"userEnteredFormat": {
                              "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                              "textFormat": {"fontFamily": "Calibri", "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                                              "bold": True, "fontSize": 11},
                              "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                          }},
                          "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                    "startIndex": 0, "endIndex": 1},
                                          "properties": {"pixelSize": 36}, "fields": "pixelSize"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid,
                                                    "gridProperties": {"frozenRowCount": 2}},
                                      "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2},
                          "cell": {"userEnteredFormat": {
                              "backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93},
                              "textFormat": {"fontFamily": "Calibri", "bold": True, "fontSize": 10,
                                              "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
                              "wrapStrategy": "WRAP",
                          }},
                          "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 2},
                          "cell": {"userEnteredFormat": {
                              "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                              "textFormat": {"fontFamily": "Calibri", "bold": False, "fontSize": 10,
                                              "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
                              "wrapStrategy": "WRAP",
                          }},
                          "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)"}},
    ]}).execute()
    print(f"\nPushed {len(auc)} clean auctions to Elon_Auctions_Inventory")


if __name__ == "__main__":
    main()
