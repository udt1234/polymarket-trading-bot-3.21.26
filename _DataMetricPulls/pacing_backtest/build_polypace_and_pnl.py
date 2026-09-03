# -*- coding: utf-8 -*-
"""Surgical update of 'Buy+Sell Pace': fill Poly Pace (col I) = market's implied final count, and add
Realized P&L (X), Running P&L (Y), Hold? (Z). Touches only those columns; leaves everything else."""
import os, glob, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
from google.oauth2 import service_account
from googleapiclient.discovery import build
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; PMX=ROOT+"/_DataMetricPulls/pmxt_pulled"
OUT=ROOT+"/_DataMetricPulls/pacing_backtest/audit_out3"; ET=ZoneInfo('America/New_York'); con=duckdb.connect()
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'
SLUG='elon-musk-of-tweets-april-23-april-25'; s=int(pd.Timestamp(datetime(2026,4,23,12,tzinfo=ET)).timestamp()); e=int(pd.Timestamp(datetime(2026,4,25,12,tzinfo=ET)).timestamp())
def pbk(l):
    l=str(l).strip()
    if l.startswith('<'): return (0,int(l[1:])-1)
    if l.endswith('+'): return (int(l[:-1]),10**9)
    if '-' in l: a,b=l.split('-'); return (int(a),int(b))
    return (int(l),int(l))
def bmid(l):
    lo,hi=pbk(l); return lo+12.0 if hi>=10**9 else ((hi+1)/2.0 if lo==0 else (lo+hi)/2.0)
row=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
row=row[row.auction_slug==SLUG].iloc[0]; tok=row.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
fs=[]; tt=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
while tt<=end: fs+=glob.glob(PMX+f"/pmxt_tweets_{tt.strftime('%Y-%m-%dT%H')}*.parquet"); tt=tt+dt.timedelta(hours=1)
arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in sorted(set(fs)))+']'; t2l={str(v):k for k,v in tok.items()}; tl='('+','.join("'"+str(v)+"'" for v in tok.values())+')'
px=con.execute(f"""SELECT ts,CAST(asset_id AS VARCHAR) aid,best_bid,best_ask FROM read_parquet({arr},union_by_name=true) WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {tl} AND best_ask>0 AND best_ask<1 AND best_bid>0 AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df(); px['lab']=px.aid.map(t2l)
B={l:{'ts':g.ts.to_numpy().astype('int64'),'mid':((g.best_bid+g.best_ask)/2).to_numpy(float)} for l,g in px.groupby('lab')}
def poly_pace(tms):
    num=den=0.0
    for l,d in B.items():
        i=np.searchsorted(d['ts'],tms,'right')-1
        if i>=0: m=d['mid'][i]; num+=m*bmid(l); den+=m
    return round(num/den,1) if den>0 else ''
tr=pd.read_csv(OUT+"/one_auction_trades_react.csv"); n=len(tr)
Ivals=[]; Xvals=[]; Yvals=[]; Zvals=[]
for i,r in tr.iterrows():
    R=i+3; p=r['et'].split(); d=p[0].split('-'); tm=p[1].split(':')
    tms=int(pd.Timestamp(datetime(2026,int(d[0]),int(d[1]),int(tm[0]),int(tm[1]),int(tm[2]),tzinfo=ET)).timestamp())*1000
    Ivals.append([poly_pace(tms)]); Xvals.append([r['rpnl']]); Yvals.append([f"=SUM($X$3:X{R})"]); Zvals.append(["Yes" if r['held'] else "No"])
data=[
 {'range':"'Buy+Sell Pace'!I2",'values':[["What Polymarket was pacing = the market's implied FINAL count (price-weighted center of all brackets at this moment)"]]},
 {'range':f"'Buy+Sell Pace'!I3:I{n+2}",'values':Ivals},
 {'range':"'Buy+Sell Pace'!X1",'values':[["Realized P&L ($)"]]},{'range':"'Buy+Sell Pace'!X2",'values':[["Actual profit/loss REALIZED by this trade. Sells realize the gain/loss; buys are 0 (position still open)"]]},{'range':f"'Buy+Sell Pace'!X3:X{n+2}",'values':Xvals},
 {'range':"'Buy+Sell Pace'!Y1",'values':[["Running P&L ($)"]]},{'range':"'Buy+Sell Pace'!Y2",'values':[["Cumulative realized P&L through this row [formula]"]]},{'range':f"'Buy+Sell Pace'!Y3:Y{n+2}",'values':Yvals},
 {'range':"'Buy+Sell Pace'!Z1",'values':[["Hold?"]]},{'range':"'Buy+Sell Pace'!Z2",'values':[["Yes = a BUY-HOLD-PACE position held to resolution (never actively sold)"]]},{'range':f"'Buy+Sell Pace'!Z3:Z{n+2}",'values':Zvals},
]
sh.spreadsheets().values().batchUpdate(spreadsheetId=SEE,body={'valueInputOption':'USER_ENTERED','data':data}).execute()
def gid(t):
    for x in sh.spreadsheets().get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
g=gid('Buy+Sell Pace'); DARK={'red':0.13,'green':0.18,'blue':0.22}; GRAY={'red':0.92,'green':0.92,'blue':0.92}; reqs=[]
# copy number format: H (Our Pace) -> I (Poly Pace); U (Total value $) -> X and Y
def cp(src_c,dst_c):
    return {'copyPaste':{'source':{'sheetId':g,'startRowIndex':2,'endRowIndex':3,'startColumnIndex':src_c,'endColumnIndex':src_c+1},
        'destination':{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':dst_c,'endColumnIndex':dst_c+1},'pasteType':'PASTE_FORMAT'}}
reqs+=[cp(7,8), cp(20,23), cp(20,24)]   # H->I, U->X, U->Y
# header (row1) dark for new cols X,Y,Z ; desc (row2) gray for I,X,Y,Z
for c in (23,24,25):
    reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':c,'endColumnIndex':c+1},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
for c in (8,23,24,25):
    reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':c,'endColumnIndex':c+1},'cell':{'userEnteredFormat':{'backgroundColor':GRAY,'textFormat':{'italic':True,'fontSize':9},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
# green/red on Realized + Running P&L
for c in (23,24):
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':c,'endColumnIndex':c+1}],'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'0'}]},'format':{'textFormat':{'foregroundColor':{'red':0.7,'green':0,'blue':0}}}}},'index':0}})
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':c,'endColumnIndex':c+1}],'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'0'}]},'format':{'textFormat':{'foregroundColor':{'red':0,'green':0.5,'blue':0}}}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print(f"DONE. Poly Pace filled ({n} rows), Realized P&L + Running P&L + Hold? added. Running total ends at ${tr.rpnl.sum():+.2f}")
