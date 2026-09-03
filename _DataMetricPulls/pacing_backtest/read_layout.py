# -*- coding: utf-8 -*-
"""Read current New_Backtest_Clean layout (headers A:AZ) + the April 16-18 row range, so the build is exact."""
import os, sys, string
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds).spreadsheets(); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
def A1(i):
    s=''; i+=1
    while i>0: i,r=divmod(i-1,26); s=chr(65+r)+s
    return s
def clean(x): return ''.join(c for c in str(x) if ord(c)<128)
r1=(sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!A1:AZ1").execute().get('values',[[]]) or [[]])[0]
r2=(sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!A2:AZ2").execute().get('values',[[]]) or [[]])[0]
mx=max(len(r1),len(r2))
print("col | ROW1 | ROW2")
for i in range(mx):
    a=r1[i] if i<len(r1) else ''; b=r2[i] if i<len(r2) else ''
    if a or b: print(f"{A1(i):>3} | {clean(a)[:30]:<30} | {clean(b)[:44]}")
# April 16-18 rows: read col A (date) + col B (time) to find the block
A=sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!A3:A2000",valueRenderOption='FORMATTED_VALUE').execute().get('values',[])
dates=[ (i+3, (r[0] if r else '')) for i,r in enumerate(A) ]
# find contiguous April 16/17/18 block
apr=[rc for rc in dates if any(d in str(rc[1]) for d in ('Apr 16','Apr 17','Apr 18'))]
print(f"\ntotal rows: {len(A)}")
if apr:
    print(f"April 16-18 rows: {apr[0][0]}..{apr[-1][0]}  ({len(apr)} rows)  first date '{apr[0][1]}' last '{apr[-1][1]}'")
# show the distinct dates in order (auction boundaries)
seen=[];
for rc in dates:
    d=str(rc[1])
    if d and (not seen or seen[-1][0]!=d): seen.append((d,rc[0]))
print("date blocks (date -> first row):")
for d,row in seen[:12]: print(f"   {d} -> row {row}")
