# -*- coding: utf-8 -*-
"""SURGICAL: append the real market quote (best BID + best ASK) at each trade's moment to the seesaw
Every Trade tab. Reads the live sheet's own Date/Time/Bracket per row (robust to any reordering),
looks up the bracket's best_ask/best_bid from the pmxt L2 at that timestamp, writes ONLY the two new
columns. The 'actual asking price' Sir wants = Best ask (that is what PM Odds already equals for buys)."""
import os, glob, json, string
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
from google.oauth2 import service_account
from googleapiclient.discovery import build
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"; ET=ZoneInfo('America/New_York')
con=duckdb.connect(); MON=['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; SLUG='elon-musk-of-tweets-april-16-april-18'
s=int(pd.Timestamp(datetime(2026,4,16,12,tzinfo=ET)).timestamp()); e=int(pd.Timestamp(datetime(2026,4,18,12,tzinfo=ET)).timestamp())
def pbk(l):
    l=str(l).strip()
    if l.startswith('<'): return (0,int(l[1:])-1)
    if l.endswith('+'): return (int(l[:-1]),10**9)
    if '-' in l: a,b=l.split('-'); return (int(a),int(b))
    return (int(l),int(l))
# pmxt YES ticks for this auction, per bracket
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
row=auc[auc.auction_slug==SLUG].iloc[0]; tok=row.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
import datetime as dt
files=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
while t<=end: files+=glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in sorted(set(files)))+']'
tok2lab={str(v):k for k,v in tok.items()}; toklist='('+','.join("'"+str(v)+"'" for v in tok.values())+')'
px=con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
    WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1 AND best_bid>0
    AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
px['lab']=px.aid.map(tok2lab)
B={}
for l in tok:
    sub=px[px.lab==l]
    if len(sub): B[l]={'ts':sub.ts.to_numpy().astype('int64'),'bid':sub.best_bid.to_numpy(float),'ask':sub.best_ask.to_numpy(float)}
def quote(lab,t_ms):
    d=B.get(lab)
    if not d: return '',''
    i=np.searchsorted(d['ts'],t_ms,side='right')-1
    if i<0: return '',''
    return round(float(d['bid'][i]),3),round(float(d['ask'][i]),3)
def parse_ts(date_str,time_str):
    mo=MON.index(date_str.split()[0]); da=int(date_str.split()[1])
    tk=time_str.replace(',',' ').split(); ht=tk[0]; ap=ht[-2:]; h=int(ht[:-2])
    if ap=='PM' and h!=12: h+=12
    if ap=='AM' and h==12: h=0
    mm=int(tk[1]); ss=int(tk[3])
    return int(pd.Timestamp(datetime(2026,mo,da,h,mm,ss,tzinfo=ET)).timestamp())*1000
# read the live rows (Date A, Time B, Bracket F)
rows=sh.spreadsheets().values().get(spreadsheetId=SEE,range="'Every Trade'!A3:F",valueRenderOption='FORMATTED_VALUE').execute().get('values',[])
bids=[]; asks=[]
for r in rows:
    r=(list(r)+['']*6)[:6]
    try:
        tms=parse_ts(r[0],r[1]); b,a=quote(r[5],tms)
    except Exception: b,a='',''
    bids.append([b]); asks.append([a])
n=len(rows)
data=[
 {'range':"'Every Trade'!T1",'values':[["Best ask (buy price)"]]},{'range':"'Every Trade'!T2",'values':[["The actual lowest ASK at this moment - what you pay to BUY 1 share. (= PM Odds for buy rows)"]]},{'range':f"'Every Trade'!T3:T{n+2}",'values':asks},
 {'range':"'Every Trade'!U1",'values':[["Best bid (sell price)"]]},{'range':"'Every Trade'!U2",'values':[["The actual highest BID at this moment - what you get SELLING 1 share. Ask minus bid = the spread"]]},{'range':f"'Every Trade'!U3:U{n+2}",'values':bids},
]
sh.spreadsheets().values().batchUpdate(spreadsheetId=SEE,body={'valueInputOption':'RAW','data':data}).execute()
def gid(t):
    for x in sh.spreadsheets().get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
sid=gid('Every Trade'); DARK={'red':0.13,'green':0.18,'blue':0.22}; GRAY={'red':0.92,'green':0.92,'blue':0.92}; reqs=[]
for ci in (19,20):
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':ci,'endColumnIndex':ci+1},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':ci,'endColumnIndex':ci+1},'cell':{'userEnteredFormat':{'backgroundColor':GRAY,'textFormat':{'italic':True,'fontSize':9},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':130},'fields':'pixelSize'}})
sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print(f"DONE {n} rows. sample: bracket {rows[0][5]} at {rows[0][0]} {rows[0][1]} -> ask {asks[0][0]}  bid {bids[0][0]}")
