"""Build the Elon Event Catalog Google Sheet (Phase 1 for QA).

Categories included: Tesla earnings + P&D + shareholder + product | SpaceX Starship |
xAI major | Court | Political. Skip Falcon 9 Starlink batches (noise).

Data window: Sept 2025 -> Dec 2026, matches Elon X-API clean data window.

Output: new Google Sheet in darwin@xagency.com's Drive, one tab "Events".
Columns: date, start_et, end_et, event, category, expected_pattern,
confidence, historical_notes, source_url, qa_status, alert_enabled.
"""
import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

TITLE = "Elon Event Catalog - Posting Behavior (Phase 1 QA)"

# Pattern legend:
#   DARK        = silent (unusual quiet during event)
#   NORMAL      = his baseline ~60/day cadence
#   STORM_AFTER = burst after event ends (reactions, metrics, victory laps)
#   LIVE_TWEET  = actively tweets during event (launches, product reveals)

EVENTS = [
    # === HISTORICAL (Sep 2025 -> now) - VERIFIED ===
    ("2025-10-02", "07:00", "09:00", "Tesla Q3 2025 P&D Report",         "Tesla",    "STORM_AFTER", "verified", "Quarterly delivery numbers - Elon typically tweets metrics reactions.", "https://ir.tesla.com/"),
    ("2025-10-13", "18:00", "20:00", "SpaceX Starship IFT-11",           "SpaceX",   "LIVE_TWEET",  "verified", "Live-tweets launch coverage, pics, engine data.", "https://en.wikipedia.org/wiki/Starship_flight_test_11"),
    ("2025-10-15", "10:00", "12:00", "Delaware Supreme Court Oral Args (Tornetta)", "Court", "STORM_AFTER", "verified", "$56B pay package appeal - Elon typically silent during, posts reactions after.", "https://clsbluesky.law.columbia.edu/2025/10/21/the-fight-over-musks-pay-delaware-supreme-court-hears-arguments-on-appeal/"),
    ("2025-10-22", "17:30", "19:30", "Tesla Q3 2025 Earnings Call",      "Tesla",    "STORM_AFTER", "verified", "5:30 PM ET call - typically DARK during 2h call, STORM after with metrics + reactions.", "https://www.sec.gov/Archives/edgar/data/1318605/000162828025000007/exhibit991.htm"),
    ("2025-11-06", "16:00", "18:30", "Tesla 2025 Annual Shareholder Meeting", "Tesla", "LIVE_TWEET", "verified", "Cybercab, Roadster, AI5 announced - live tweets throughout.", "https://teslanorth.com/2025/11/07/tesla-2025-annual-shareholder-meeting-everything-you-need-to-know/"),
    ("2025-12-19", "10:00", "16:00", "Delaware Supreme Court Ruling (Musk Wins Pay Case)", "Court", "STORM_AFTER", "verified", "$56B package reinstated - EXPECT massive victory-lap posting.", "https://www.cnbc.com/2025/12/19/musk-tesla-pay-delaware-supreme-court.html"),

    ("2026-01-02", "07:00", "09:00", "Tesla Q4 2025 P&D Report",         "Tesla",    "STORM_AFTER", "verified", "Delivery numbers reaction posts.", "https://ir.tesla.com/"),
    ("2026-01-28", "17:30", "19:30", "Tesla Q4 2025 Earnings Call",      "Tesla",    "STORM_AFTER", "verified", "Full-year 2025 results.", "https://www.bloomberg.com/news/live-blog/2026-01-28/tesla-fourth-quarter-earnings"),

    ("2026-03-03", "12:00", "18:00", "Grok 4.20 Beta 2 Launch",          "xAI",      "STORM_AFTER", "verified", "Product launch - heavy promo posts.", "https://www.digitalapplied.com/blog/grok-4-20-preview-xai-musk-roadmap"),

    ("2026-04-01", "17:00", "20:00", "Tesla Roadster Unveil",            "Tesla",    "LIVE_TWEET",  "verified", "Product reveal event - live tweets throughout.", "https://insideevs.com/news/778232/tesla-cybercab-production-april-2026/"),
    ("2026-04-02", "07:00", "09:00", "Tesla Q1 2026 P&D Report",         "Tesla",    "STORM_AFTER", "verified", "Delivery numbers.", "https://www.cnbc.com/2026/04/02/tesla-tsla-q1-2026-vehicle-delivery-production.html"),
    ("2026-04-22", "17:30", "19:30", "Tesla Q1 2026 Earnings Call",      "Tesla",    "STORM_AFTER", "verified", "Earnings call after market close.", "https://www.sec.gov/Archives/edgar/data/1318605/000162828026000016/exhibit9914.htm"),
    ("2026-04-30", "12:00", "18:00", "Grok 4.3 Release",                 "xAI",      "STORM_AFTER", "verified", "1M context, native video input, PDF/PPTX/XLSX generation.", "https://en.wikipedia.org/wiki/Grok_(chatbot)"),

    ("2026-05-21", "18:00", "20:30", "SpaceX Starship IFT-12 (v3 debut)","SpaceX",   "LIVE_TWEET",  "verified", "First v3 flight - taller booster + upper stage. Live tweets guaranteed.", "https://spacepolicyonline.com/events/spacex-starship-integrated-flight-test-12-ift-12-may-19-2026-starbase-tx-630-pm-et/"),

    ("2026-06-28", "00:00", "23:59", "Elon Musk 55th Birthday",          "Personal", "STORM_AFTER", "verified", "Historically posts MORE, not less. See elon_cadence_baseline memory.", "internal"),

    ("2026-07-02", "07:00", "09:00", "Tesla Q2 2026 P&D Report",         "Tesla",    "STORM_AFTER", "verified", "480k deliveries.", "https://www.businesswire.com/news/home/20260702058054/en/Tesla-Second-Quarter-2026-Production-Deliveries-Deployments"),
    ("2026-07-16", "14:00", "16:00", "SpaceX Starship IFT-13 (anomaly)", "SpaceX",   "STORM_AFTER", "verified", "Post-ignition anomaly abort - post-mortem/reaction posts expected.", "https://grokipedia.com/page/2026_in_spaceflight"),
    ("2026-07-22", "17:30", "19:30", "Tesla Q2 2026 Earnings Call",      "Tesla",    "STORM_AFTER", "verified", "Q2 2026 earnings after market close.", "https://capital.com/en-int/analysis/tesla-earnings-date"),

    # === UPCOMING (Aug 2026 -> Dec 2026) - PROJECTED ===
    ("2026-10-02", "07:00", "09:00", "Tesla Q3 2026 P&D Report",         "Tesla",    "STORM_AFTER", "projected", "Quarterly - Elon posts metrics reactions. Date approximate.", "https://ir.tesla.com/"),
    ("2026-10-21", "17:30", "19:30", "Tesla Q3 2026 Earnings Call",      "Tesla",    "STORM_AFTER", "projected", "5:30 PM ET call - typical cadence. Date projected from Q4/Q1/Q2 pattern.", "https://ir.tesla.com/"),
    ("2026-11-05", "16:00", "18:30", "Tesla 2026 Annual Shareholder Meeting", "Tesla", "LIVE_TWEET", "projected", "Annual meeting - usually early November. Date projected.", "https://ir.tesla.com/"),

    ("2026-09-15", "12:00", "20:00", "Grok 5 Release (projected)",       "xAI",      "STORM_AFTER", "projected", "xAI targets Q3 2026; 6T param MoE, gigawatt-scale training. Date placeholder.", "https://en.wikipedia.org/wiki/Grok_(chatbot)"),

    ("2026-08-15", "18:00", "20:30", "SpaceX Starship IFT-14 (projected)","SpaceX",  "LIVE_TWEET",  "projected", "Post-IFT-13 anomaly recovery flight - date TBD. Placeholder.", "https://en.wikipedia.org/wiki/Starship_flight_test_11"),

    # === RECURRING BEHAVIORAL PATTERNS (add to sheet as reference rows) ===
    ("RECURRING", "03:00", "09:00", "Sleep Window (daily)",              "Personal", "DARK",        "verified", "Baseline: 03:00-09:00 UTC = 23:00-05:00 ET Dubai time; posts drop 60-70% vs peak hours.", "internal-cadence-baseline"),
]


def build_sheet() -> str:
    creds = service_account.Credentials.from_service_account_file(
        os.path.expanduser("~/.claude/google-service-account.json"),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    # Create sheet
    doc = sheets.spreadsheets().create(body={"properties": {"title": TITLE}}).execute()
    sid = doc["spreadsheetId"]

    # Rename first tab + write data
    meta = sheets.spreadsheets().get(spreadsheetId=sid).execute()
    gid = meta["sheets"][0]["properties"]["sheetId"]

    header = [
        "#", "Date (ET)", "Time Start", "Time End", "Event", "Category",
        "Expected Pattern", "Confidence", "Historical Notes", "Source",
        "QA Verdict (Sir fills)", "Alert Enabled? (Sir fills)"
    ]
    rows = [header]
    for i, (d, t_start, t_end, name, cat, pattern, conf, notes, src) in enumerate(EVENTS, 1):
        rows.append([i, d, t_start, t_end, name, cat, pattern, conf, notes, src, "", ""])

    sheets.spreadsheets().values().update(
        spreadsheetId=sid, range="A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    # Format: bold header, freeze row 1, auto-size cols
    sheets.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
        {"updateSheetProperties": {
            "properties": {"sheetId": gid, "title": "Events",
                          "gridProperties": {"rowCount": len(rows) + 20, "columnCount": len(header), "frozenRowCount": 1}},
            "fields": "title,gridProperties(rowCount,columnCount,frozenRowCount)",
        }},
        {"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 11,
                               "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "backgroundColor": {"red": 0.15, "green": 0.15, "blue": 0.18},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment)",
        }},
        {"autoResizeDimensions": {
            "dimensions": {"sheetId": gid, "dimension": "COLUMNS",
                          "startIndex": 0, "endIndex": len(header)}
        }},
        # Add conditional formatting for pattern column (G, index 6)
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": gid, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "DARK"}]},
                            "format": {"backgroundColor": {"red": 0.86, "green": 0.85, "blue": 0.99}}},
        }, "index": 0}},
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": gid, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "STORM_AFTER"}]},
                            "format": {"backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.4}}},
        }, "index": 0}},
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": gid, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "LIVE_TWEET"}]},
                            "format": {"backgroundColor": {"red": 0.7, "green": 0.9, "blue": 0.7}}},
        }, "index": 0}},
    ]}).execute()

    meta = drive.files().get(fileId=sid, fields="webViewLink").execute()
    return meta["webViewLink"]


if __name__ == "__main__":
    url = build_sheet()
    print(f"SHEET_URL: {url}")
