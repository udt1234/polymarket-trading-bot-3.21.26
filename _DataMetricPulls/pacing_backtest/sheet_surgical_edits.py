# -*- coding: utf-8 -*-
"""SURGICAL edits to the seesaw Every Trade tab (touches ONLY A,B,C and a new last column R):
 - split A (date+time) -> A=date, B=clock time ("4PM 24 mins, 20 seconds")
 - C (time to close) -> verbose ("19 hrs, 35 mins")
 - new last column R = what EACH of our pace models is projecting the FINAL count to be, per row
Reads the live sheet, writes only those cells. Everything else (D..Q, your blanks/renames) untouched."""
import os, glob, json
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; ET=ZoneInfo('America/New_York')
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'
MON=['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
s=int(pd.Timestamp(datetime(2026,4,16,12,tzinfo=ET)).timestamp()); e=int(pd.Timestamp(datetime(2026,4,18,12,tzinfo=ET)).timestamp()); total=48.0
# priors (same as single_auction_seesaw): rmean/Kk from prior 2-day auctions, share = walk-forward accrual curve
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0=int(pts.min())
def obs(a,b): return int(np.searchsorted(pts,b)-np.searchsorted(pts,a))
def noon(slug):
    tk=str(slug).replace('elon-musk-of-tweets-','').split('-'); M={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
    mo1=M[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in M: mo2=M[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
allA=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    try: w=noon(a.auction_slug)
    except Exception: w=None
    if not w or not 1.5<=(w[1]-w[0])/86400<=2.6: continue
    allA.append({'e':w[1],'final':obs(w[0],w[1])})
pr=[a['final']/48 for a in allA if a['e']<s]; rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
# walk-forward accrual curve
noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
while d.timestamp()+48*3600<=s:
    ss=int(d.timestamp()); final=obs(ss,ss+48*3600)
    if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,49)],float)/final)
    d=d+pd.Timedelta(days=1)
share=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0)
def models(o,eh,rh,cp):
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))]
    ens=(1-cp)*kal+cp*acc
    cap=o+min((ens-o)/max(rh,.1),1.5*rmean)*rh
    return kal,acc,ens,cap

# read live A (timestamp) + G (count) for the data rows
rows=sh.spreadsheets().values().get(spreadsheetId=SEE,range="'Every Trade'!A3:G",valueRenderOption='FORMATTED_VALUE').execute().get('values',[])
dates=[]; times=[]; durs=[]; pacings=[]
for r in rows:
    r=(list(r)+['']*7)[:7]; ts=str(r[0]); cnt=r[6]
    p=ts.split(); mo,da=p[0].split('-'); hh,mm,ssx=p[1].split(':')
    mo,da,hh,mm,ssx=int(mo),int(da),int(hh),int(mm),int(ssx)
    dates.append([f"{MON[mo]} {da}"])
    ap='AM' if hh<12 else 'PM'; h12=hh%12 or 12
    times.append([f"{h12}{ap} {mm} mins, {ssx} seconds"])
    # C = time to close (hrs, e.g. '19.59')
    try:
        hc=float(r[2]); H=int(hc); M=int(round((hc-H)*60)); durs.append([f"{H} hrs, {M} mins"])
    except Exception: durs.append([''])
    # pacing models at this row
    t_sec=int(pd.Timestamp(datetime(2026,mo,da,hh,mm,ssx,tzinfo=ET)).timestamp())
    eh=max((t_sec-s)/3600.0,0.5); rh=max(total-eh,0.1); cp=eh/total
    o=int(cnt) if str(cnt).strip() not in ('','nan') else obs(s,t_sec)
    kal,acc,ens,cap=models(o,eh,rh,cp)
    pacings.append([f"Kalman {kal:.0f} · Accrual {acc:.0f} · Ensemble {ens:.0f} · Ens+Cap1.5 {cap:.0f}"])
n=len(rows)
data=[
 {'range':"'Every Trade'!A1",'values':[["Date"]]},{'range':"'Every Trade'!A2",'values':[["Calendar date of the trade"]]},{'range':f"'Every Trade'!A3:A{n+2}",'values':dates},
 {'range':"'Every Trade'!B1",'values':[["Time"]]},{'range':"'Every Trade'!B2",'values':[["Clock time of the trade (ET)"]]},{'range':f"'Every Trade'!B3:B{n+2}",'values':times},
 {'range':"'Every Trade'!C1",'values':[["Time to close"]]},{'range':"'Every Trade'!C2",'values':[["How long until the auction resolves"]]},{'range':f"'Every Trade'!C3:C{n+2}",'values':durs},
 {'range':"'Every Trade'!R1",'values':[["Pacing strategies (now projecting)"]]},{'range':"'Every Trade'!R2",'values':[["What EACH of our pace models projects the FINAL count to be at this moment (Ens+Cap1.5 is the locked one = the 'Our Pace' column)"]]},{'range':f"'Every Trade'!R3:R{n+2}",'values':pacings},
]
sh.spreadsheets().values().batchUpdate(spreadsheetId=SEE,body={'valueInputOption':'RAW','data':data}).execute()
# light formatting for the new column R + A/B/C widths (does not touch D..Q)
def gid(t):
    for x in sh.spreadsheets().get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
sid=gid('Every Trade'); DARK={'red':0.13,'green':0.18,'blue':0.22}; GRAY={'red':0.92,'green':0.92,'blue':0.92}; reqs=[]
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':17,'endColumnIndex':18},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':17,'endColumnIndex':18},'cell':{'userEnteredFormat':{'backgroundColor':GRAY,'textFormat':{'italic':True,'fontSize':9},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
for ci,w in [(0,90),(1,200),(2,150),(17,300)]:
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':w},'fields':'pixelSize'}})
sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print(f"DONE {n} rows. sanity row1: date={dates[0][0]} time={times[0][0]} close={durs[0][0]} | {pacings[0][0]}")
