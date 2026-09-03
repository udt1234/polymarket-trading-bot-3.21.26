# -*- coding: utf-8 -*-
"""Clean rebuild of the seesaw sheet's Every Trade + Per-Post Pace tabs FROM SOURCE (not the scrambled
sheet). Uses the corrected sigma-gated run (one_auction_trades/tweets.csv). Adds the Tweet-count column,
row-2 descriptions, and live Kelly/EV/shares/value formulas. Clears each tab first so no stale rows."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; ET=ZoneInfo('America/New_York')
D=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'
tr=pd.read_csv(f"{D}/one_auction_trades.csv"); tw=pd.read_csv(f"{D}/one_auction_tweets.csv")
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); s=int(pd.Timestamp(datetime(2026,4,16,12,tzinfo=ET)).timestamp())
def count_at(et_str):
    try:
        p=str(et_str).strip().split(); d=p[0].split('-'); tm=p[1].split(':')
        t=int(pd.Timestamp(datetime(2026,int(d[0]),int(d[1]),int(tm[0]),int(tm[1]),int(tm[2]),tzinfo=ET)).timestamp())
        return int(np.searchsorted(pts,t)-np.searchsorted(pts,s))
    except Exception: return ''
def gid(title):
    for x in sh.spreadsheets().get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==title: return x['properties']['sheetId']
DARK={'red':0.13,'green':0.18,'blue':0.22}; GRAY={'red':0.92,'green':0.92,'blue':0.92}

# ---- Every Trade ----
ehdr=['Time (ET)','Hrs to close','Action','Bracket','Tweet count (so far)','What we are pacing (count)','PM odds','Our fair','Edge','Kelly fraction','Expected value ($)','Shares','Total value ($)']
edesc=['When the trade fired (Eastern)','Hours left until the auction resolves','BUY = market below our fair; SELL = market above our fair','The tweet-count bracket traded',
 'How many tweets Elon had ACTUALLY posted at this moment (count so far)','Our projected FINAL tweet count driving this trade (our center)',
 "Polymarket's price for this bracket = the market's implied probability",'Our fair probability this bracket wins (pace + shrinking uncertainty)',
 'Our fair minus the market price. + = underpriced (buy), - = overpriced (sell)','Kelly bet fraction = edge / (1 - price)','Shares x edge = expected profit of this clip [formula]',
 'Kelly-sized: MIN(bankroll x fraction x Kelly, clip cap) / price [formula]','Shares x price = dollars deployed [formula]']
grid=[ehdr,edesc]
for i,r in tr.iterrows():
    R=i+3; tc=count_at(r['et'])
    grid.append([r['et'],r['hrs_to_close'],r['action'],r['bracket'],tc,r['our_center'],r['price'],r['our_fair'],
        f"=H{R}-G{R}", f"=(H{R}-G{R})/(1-G{R})", f"=L{R}*(H{R}-G{R})",
        f"=MIN(Config!$B$2*Config!$B$3*J{R},Config!$B$4)/G{R}", f"=L{R}*G{R}"])
sh.spreadsheets().values().clear(spreadsheetId=SEE,range="'Every Trade'!A1:Z2000").execute()
sh.spreadsheets().values().update(spreadsheetId=SEE,range="'Every Trade'!A1",valueInputOption='USER_ENTERED',body={'values':grid}).execute()

# ---- Per-Post Pace ----
phdr=['tweet_no','et','hrs_to_close','count_so_far','center_before','center_after','per_post_move','sigma']
pdesc=['Nth counted tweet in the auction','When the tweet posted (Eastern)','Hours left until resolution','Tweets counted so far',
 'Our projected final count just BEFORE this tweet','Our projected final count just AFTER this tweet','How much this ONE tweet moved our projection (accurate late, wild early)','Our uncertainty band in tweets; shrinks as time runs out']
pgrid=[phdr,pdesc]
for _,r in tw.iterrows(): pgrid.append([('' if pd.isna(r[c]) else r[c]) for c in phdr])
sh.spreadsheets().values().clear(spreadsheetId=SEE,range="'Per-Post Pace'!A1:Z2000").execute()
sh.spreadsheets().values().update(spreadsheetId=SEE,range="'Per-Post Pace'!A1",valueInputOption='USER_ENTERED',body={'values':pgrid}).execute()

# ---- formatting ----
reqs=[]
for tab,nc,nr,bs in [('Every Trade',13,len(tr),2),('Per-Post Pace',8,len(tw),None)]:
    sid=gid(tab)
    reqs.append({'updateSheetProperties':{'properties':{'sheetId':sid,'gridProperties':{'frozenRowCount':2}},'fields':'gridProperties.frozenRowCount'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':GRAY,'textFormat':{'italic':True,'fontSize':9},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
    if bs is not None:
        for val,color in [("BUY",{'red':0.83,'green':0.94,'blue':0.83}),("SELL",{'red':0.99,'green':0.90,'blue':0.80})]:
            reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':2,'endRowIndex':nr+2,'startColumnIndex':bs,'endColumnIndex':bs+1}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sid=gid('Every Trade')
for ci,w in [(0,120),(4,120),(5,150),(9,120),(10,130),(11,90),(12,100)]:
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':w},'fields':'pixelSize'}})
sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print(f"DONE. Every Trade {len(tr)} trades, Per-Post Pace {len(tw)} tweets. e.g. first trade count={count_at(tr.iloc[0]['et'])} at {tr.iloc[0]['et']}")
print("https://docs.google.com/spreadsheets/d/"+SEE+"/edit")
