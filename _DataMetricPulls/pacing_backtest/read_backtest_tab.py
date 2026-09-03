# -*- coding: utf-8 -*-
"""Read the current live state of the New_Backtest_Clean_7.13.2026 tab so we describe the document accurately."""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds).spreadsheets(); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
meta=sh.get(spreadsheetId=SEE).execute()
tabs=[(x['properties']['title'],x['properties']['sheetId']) for x in meta['sheets']]
print("TABS:", tabs)
# row count via col A, last Running P&L (col Z), realized P&L column (col W) sum
A=sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!A3:A5000").execute().get('values',[])
n=len(A)
Z=sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!Z3:Z{n+2}",valueRenderOption='FORMATTED_VALUE').execute().get('values',[])
W=sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!W3:W{n+2}",valueRenderOption='UNFORMATTED_VALUE').execute().get('values',[])
wsum=sum(float(r[0]) for r in W if r and isinstance(r[0],(int,float)))
print(f"data rows: {n}")
print(f"last Running P&L (Z{n+2}): {Z[-1][0] if Z and Z[-1] else 'blank'}")
print(f"sum Realized P&L (col W): {wsum:.2f}")
