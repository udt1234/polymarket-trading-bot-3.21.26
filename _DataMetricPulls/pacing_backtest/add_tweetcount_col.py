# -*- coding: utf-8 -*-
"""Add a 'Tweet count (so far)' column to the seesaw Every Trade tab, IN PLACE, preserving the 236
rows. Count is computed from the X-API tweet backfill = how many tweets Elon had actually posted at
each trade's timestamp. Re-lays the tab as 13 columns and re-points the Kelly/EV/shares/value formulas."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; ET=ZoneInfo('America/New_York')
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds)
SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64')
s=int(pd.Timestamp(datetime(2026,4,16,12,tzinfo=ET)).timestamp())
def count_at(et_str):
    try:
        p=str(et_str).strip().split(); d=p[0].split('-'); tm=p[1].split(':')
        t=int(pd.Timestamp(datetime(2026,int(d[0]),int(d[1]),int(tm[0]),int(tm[1]),int(tm[2]),tzinfo=ET)).timestamp())
        return int(np.searchsorted(pts,t)-np.searchsorted(pts,s))
    except Exception: return ''
def gid(title):
    for x in sh.spreadsheets().get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==title: return x['properties']['sheetId']
data=sh.spreadsheets().values().get(spreadsheetId=SEE,range="'Every Trade'!A3:G",valueRenderOption='FORMATTED_VALUE').execute().get('values',[])
hdr=['Time (ET)','Hrs to close','Action','Bracket','Tweet count (so far)','What we are pacing (count)','PM odds','Our fair','Edge','Kelly fraction','Expected value ($)','Shares','Total value ($)']
desc=['When the trade fired (Eastern)','Hours left until the auction resolves','BUY = market below our fair; SELL = market above our fair','The tweet-count bracket traded',
 'How many tweets Elon had ACTUALLY posted at this moment (count so far)','Our projected FINAL tweet count driving this trade (our center)',
 "Polymarket's price for this bracket = the market's implied probability",'Our fair probability this bracket wins (pace + shrinking uncertainty)',
 'Our fair minus the market price. + = underpriced (buy), - = overpriced (sell)','Kelly bet fraction = edge / (1 - price)','Shares x edge = expected profit of this clip [formula]',
 'Kelly-sized: MIN(bankroll x fraction x Kelly, clip cap) / price [formula]','Shares x price = dollars deployed [formula]']
grid=[hdr,desc]
for i,e in enumerate(data):
    e=(list(e)+['']*7)[:7]
    R=i+3
    tc=count_at(str(e[0]))
    grid.append([e[0],e[1],e[2],e[3], tc, e[4], e[5], e[6],
        f"=H{R}-G{R}", f"=(H{R}-G{R})/(1-G{R})", f"=L{R}*(H{R}-G{R})",
        f"=MIN(Config!$B$2*Config!$B$3*J{R},Config!$B$4)/G{R}", f"=L{R}*G{R}"])
sh.spreadsheets().values().update(spreadsheetId=SEE,range="'Every Trade'!A1",valueInputOption='USER_ENTERED',body={'values':grid}).execute()
sid=gid('Every Trade'); reqs=[]
DARK={'red':0.13,'green':0.18,'blue':0.22}; GRAY={'red':0.92,'green':0.92,'blue':0.92}
reqs.append({'updateSheetProperties':{'properties':{'sheetId':sid,'gridProperties':{'frozenRowCount':2}},'fields':'gridProperties.frozenRowCount'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':13},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':0,'endColumnIndex':13},'cell':{'userEnteredFormat':{'backgroundColor':GRAY,'textFormat':{'italic':True,'fontSize':9},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
for val,color in [("BUY",{'red':0.83,'green':0.94,'blue':0.83}),("SELL",{'red':0.99,'green':0.90,'blue':0.80})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':2,'endRowIndex':len(data)+2,'startColumnIndex':2,'endColumnIndex':3}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
for ci,w in [(0,120),(4,120),(5,150),(9,120),(10,130),(11,90),(12,100)]:
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':w},'fields':'pixelSize'}})
sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print("DONE rows:",len(data),"| first trade count:",count_at(str(data[0][0])),"at",data[0][0])
print("https://docs.google.com/spreadsheets/d/"+SEE+"/edit")
