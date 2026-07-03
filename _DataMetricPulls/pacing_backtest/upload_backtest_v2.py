"""Upload backtest_full_results.csv + summary to _Backtest_Pacing tab.

Layout:
  Row 1: Title bar (description of what this tab is)
  Row 2: Headers
  Row 3: Layman description per column
  Row 4: Summary (mean abs err % per model column)
  Row 5+: One auction per row
"""
import os, sys, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
from google.oauth2 import service_account
from googleapiclient.discovery import build

creds = service_account.Credentials.from_service_account_file(
    os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc = build('sheets','v4',credentials=creds)
SHEET_ID = '1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8'
TAB = '_Backtest_Pacing'

OUT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\pacing_backtest')
df = pd.read_csv(OUT/'backtest_full_results.csv')
print(f'Loaded {len(df)} rows, {len(df.columns)} columns')

# Build header + description + summary
headers = list(df.columns)

# Descriptions per column
DESC = {
    'auction_slug': 'Polymarket event slug',
    'duration_type': '2-day / 7-day / monthly',
    'start_utc': 'When auction window opened',
    'end_utc': 'When auction window closed',
    'total_hours': 'Auction length in hours',
    'actual': "Real final tweet count — the 'answer key' each model tries to predict",
    'winning_bucket': 'Which bracket resolved YES',
}

MODEL_DESC = {
    'Linear': 'Naive: observed × total_h / elapsed_h',
    'CurBayes': "vAI's deployed precision-weighted Bayes blend",
    'M0': 'Bayesian Gamma-Poisson (classic conjugate update on tweet rate)',
    'M1Seas': 'Hour-of-day × DoW expected rate from history',
    'Decay': 'M0 with exponential decay on older auctions (ε=0.85)',
    'M2Hawk': 'Hawkes self-exciting point process — tweets trigger more tweets',
    'M3Hawk': 'Marked Hawkes — excitation scaled by tweet type (repost vs quote)',
    'M4MMPP': '2-state quiet/manic regime (mean-revert with prior rate)',
    'M5NB': 'Negative Binomial on prior totals with pacing adjustment',
    'Kalman': 'Kalman filter on latent tweet rate (1D state-space)',
}

descriptions = []
for h in headers:
    if h in DESC:
        descriptions.append(DESC[h])
    elif h.endswith('_err%'):
        descriptions.append(f"How wrong was the prediction at this checkpoint, as % of actual")
    else:
        # Parse model + checkpoint
        for m, mdesc in MODEL_DESC.items():
            if h.startswith(m):
                cp = 'T-2d' if '_T2d' in h else 'T-1d'
                descriptions.append(f'{mdesc}. Snapshotted at {cp}.')
                break
        else:
            descriptions.append('')

# Summary row: mean abs err % per err column
summary = []
for h in headers:
    if h.endswith('_err%'):
        vals = pd.to_numeric(df[h], errors='coerce').dropna()
        summary.append(round(vals.mean(), 1) if len(vals) else '')
    elif h == 'auction_slug':
        summary.append('MEAN ABS ERR %')
    else:
        summary.append('')

# Title row
title = [f'Full Python backtest on canonical Elon data — {len(df)} auctions, 10 models, walk-forward fair (T-2d + T-1d snapshots). Filter: confidence=high.']
title += [''] * (len(headers) - 1)

# Build full payload
rows = df.values.tolist()
# Replace NaN with ''
rows_clean = [[('' if (isinstance(c, float) and pd.isna(c)) else c) for c in row] for row in rows]
payload = [title, headers, descriptions, summary] + rows_clean

# Clear and write
svc.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range=f'{TAB}!A1:BZ500').execute()
svc.spreadsheets().values().update(spreadsheetId=SHEET_ID, range=f'{TAB}!A1',
    valueInputOption='RAW', body={'values': payload}).execute()
print(f'Wrote {len(payload)} rows to {TAB}')

# Format: title row purple, headers grey bold, descriptions blue italic, summary yellow bold, freeze top 4
meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID, fields='sheets(properties(title,sheetId))').execute()
tab_id = next(s['properties']['sheetId'] for s in meta['sheets'] if s['properties']['title']==TAB)

svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={'requests': [
    # Row 1: title — bold purple-ish, merged
    {'repeatCell': {
        'range': {'sheetId': tab_id, 'startRowIndex': 0, 'endRowIndex': 1},
        'cell': {'userEnteredFormat': {
            'textFormat': {'bold': True, 'fontSize': 11, 'foregroundColor': {'red':1,'green':1,'blue':1}},
            'backgroundColor': {'red':0.4,'green':0.3,'blue':0.6},
        }},
        'fields': 'userEnteredFormat(textFormat,backgroundColor)'
    }},
    {'mergeCells': {
        'range': {'sheetId': tab_id, 'startRowIndex': 0, 'endRowIndex': 1, 'startColumnIndex': 0, 'endColumnIndex': len(headers)},
        'mergeType': 'MERGE_ALL'
    }},
    # Row 2: headers
    {'repeatCell': {
        'range': {'sheetId': tab_id, 'startRowIndex': 1, 'endRowIndex': 2},
        'cell': {'userEnteredFormat': {'textFormat': {'bold': True}, 'backgroundColor': {'red':0.85,'green':0.85,'blue':0.85}}},
        'fields': 'userEnteredFormat(textFormat,backgroundColor)'
    }},
    # Row 3: descriptions
    {'repeatCell': {
        'range': {'sheetId': tab_id, 'startRowIndex': 2, 'endRowIndex': 3},
        'cell': {'userEnteredFormat': {
            'textFormat': {'italic': True, 'fontSize': 9},
            'backgroundColor': {'red':0.88,'green':0.95,'blue':1.0},
            'wrapStrategy': 'WRAP',
            'verticalAlignment': 'TOP'
        }},
        'fields': 'userEnteredFormat(textFormat,backgroundColor,wrapStrategy,verticalAlignment)'
    }},
    # Row 4: summary
    {'repeatCell': {
        'range': {'sheetId': tab_id, 'startRowIndex': 3, 'endRowIndex': 4},
        'cell': {'userEnteredFormat': {'textFormat': {'bold': True}, 'backgroundColor': {'red':1.0,'green':0.95,'blue':0.7}}},
        'fields': 'userEnteredFormat(textFormat,backgroundColor)'
    }},
    # Description row height
    {'updateDimensionProperties': {
        'range': {'sheetId': tab_id, 'dimension': 'ROWS', 'startIndex': 2, 'endIndex': 3},
        'properties': {'pixelSize': 100},
        'fields': 'pixelSize'
    }},
    # Freeze top 4
    {'updateSheetProperties': {
        'properties': {'sheetId': tab_id, 'gridProperties': {'frozenRowCount': 4}},
        'fields': 'gridProperties.frozenRowCount'
    }},
]}).execute()
print('Formatting applied')

# Print leaderboard
print('\n=== Leaderboard (mean abs error %) ===')
models = ['Linear','CurBayes','M0','M1Seas','Decay','M2Hawk','M3Hawk','M4MMPP','M5NB','Kalman']
table = []
for m in models:
    t2 = f'{m}_T2d_err%'; t1 = f'{m}_T1d_err%'
    t2v = pd.to_numeric(df[t2], errors='coerce').dropna() if t2 in df.columns else pd.Series([])
    t1v = pd.to_numeric(df[t1], errors='coerce').dropna() if t1 in df.columns else pd.Series([])
    table.append((m, t2v.mean() if len(t2v) else 999, t1v.mean() if len(t1v) else 999, len(t2v), len(t1v)))
table.sort(key=lambda x: x[1])
print(f"{'Rank':<4} {'Model':<10} {'T-2d err%':>10} {'T-1d err%':>10} {'n_T2d':>6} {'n_T1d':>6}")
for i, (m, t2, t1, n2, n1) in enumerate(table):
    print(f"{i+1:<4} {m:<10} {t2:>10.1f} {t1:>10.1f} {n2:>6} {n1:>6}")
