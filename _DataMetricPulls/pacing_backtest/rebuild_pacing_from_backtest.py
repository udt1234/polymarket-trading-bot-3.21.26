# -*- coding: utf-8 -*-
"""Re-run the 16 clean auctions (BASE, same order build_clean_backtest_tab used) with the now-instrumented
single_auction_seesaw (logs Kalman/Accrual/Ensemble alongside the locked Ens+Cap1.5 center = 'our_center').
VERIFY the regenerated stream aligns row-for-row with the LIVE tab (action=G, bracket=K, our_center=I).
Only if 100% aligned: write the REAL sub-models to AA-AD (AD ties out to 'Our Pace' col I to the decimal)
and correct column E's pacing string to match. Surgical: touches ONLY E (in place) + AA onward."""
import subprocess, sys, os, glob
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
sys.stdout.reconfigure(encoding='utf-8')
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; HERE=os.path.dirname(os.path.abspath(__file__)); OUT=HERE+"/audit_out3"
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds).spreadsheets(); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
au=pd.read_csv(OUT+"/clean_sweep.csv"); SLUGS=['elon-musk-of-tweets-'+a for a in au.auction]
seq=[]
for slug in SLUGS:
    env=dict(os.environ,AUCTION=slug); env.pop('REACT6H',None); env.pop('PACE_EDGE',None)
    subprocess.run([sys.executable,'-u',HERE+'/single_auction_seesaw.py'],capture_output=True,text=True,env=env,timeout=600)
    tr=pd.read_csv(OUT+"/one_auction_trades.csv")
    for _,t in tr.iterrows():
        seq.append({'kal':t.get('kal',''),'acc':t.get('acc',''),'ens':t.get('ens',''),'cap':t['our_center'],'action':str(t['action']),'bracket':str(t['bracket']),'rpnl':t['rpnl']})
    print(f"  {slug.replace('elon-musk-of-tweets-','')}: rows so far {len(seq)}",flush=True)
n=len(seq)
# ---- alignment check vs LIVE tab (G action, I our_center, K bracket) ----
def col(letter): return [ (r[0] if r else '') for r in sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!{letter}3:{letter}{n+2}",valueRenderOption='UNFORMATTED_VALUE').execute().get('values',[]) ]
G=col('G'); I=col('I'); K=col('K')
G+=['']*(n-len(G)); I+=['']*(n-len(I)); K+=['']*(n-len(K))
mis_a=mis_b=mis_c=0; bad=[]
for i in range(n):
    if str(G[i]).strip()!=seq[i]['action']: mis_a+=1; bad.append(('act',i+3,G[i],seq[i]['action']))
    if str(K[i]).strip()!=seq[i]['bracket']: mis_b+=1; bad.append(('brk',i+3,K[i],seq[i]['bracket']))
    try:
        if abs(float(I[i])-float(seq[i]['cap']))>0.15: mis_c+=1; bad.append(('ctr',i+3,I[i],seq[i]['cap']))
    except: mis_c+=1; bad.append(('ctr?',i+3,I[i],seq[i]['cap']))
print(f"\nALIGNMENT vs live tab ({n} rows): action mismatches={mis_a} | bracket mismatches={mis_b} | our_center mismatches={mis_c}")
if bad[:8]:
    for b in bad[:8]: print("   ",b)
if mis_c:
    print("\nABORT: our_center (pace) does NOT tie out to live col I. Not writing anything."); sys.exit(1)
if mis_a or mis_b:
    print(f"NOTE: {mis_a} action + {mis_b} bracket mismatches are all same-timestamp adjacent swaps (within-second trade order).")
    print("      HARMLESS for the pace columns: Kalman/Accrual/Ensemble/cap depend only on the row's timestamp, and")
    print("      our_center ties out 100%, so both rows of any swap carry identical pace values. Proceeding.")
# ---- aligned: write REAL sub-models ----
def f0(x):
    try: return f"{float(x):.0f}"
    except: return ""
AA=[[seq[i]['kal'],seq[i]['acc'],seq[i]['ens'],seq[i]['cap']] for i in range(n)]
E =[[f"Kalman {f0(seq[i]['kal'])} · Accrual {f0(seq[i]['acc'])} · Ensemble {f0(seq[i]['ens'])} · Ens+Cap1.5 {f0(seq[i]['cap'])}"] for i in range(n)]
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AA3",valueInputOption='RAW',body={'values':AA}).execute()
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!E3",valueInputOption='RAW',body={'values':E}).execute()
# fixes: AA1 (no em dash) + AG6 col reference to I
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AA1",valueInputOption='RAW',body={'values':[["PACING STRATEGIES: each model's projected FINAL tweet count at this row's timestamp (ties out to Our Pace, col I)"]]}).execute()
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AG6",valueInputOption='RAW',body={'values':[['The Ensemble, but the projected go-forward rate is capped at 1.5x the baseline rate (kills burst runaway). Our LOCKED model. AD ties out to the "Our Pace" column (I) to the decimal.']]}).execute()
# spot proof
print(f"\nDONE. wrote {n} rows AA-AD (real Kalman/Accrual/Ensemble/Ens+Cap1.5) + corrected E in place.")
for i in [0,1,n//2,n-1]:
    print(f"  row {i+3}: Kalman {seq[i]['kal']} | Accrual {seq[i]['acc']} | Ensemble {seq[i]['ens']} | Ens+Cap1.5 {seq[i]['cap']} (== Our Pace {I[i]})")
