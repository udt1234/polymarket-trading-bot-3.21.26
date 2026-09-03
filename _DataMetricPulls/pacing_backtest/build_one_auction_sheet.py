# -*- coding: utf-8 -*-
"""Sheet: ONE auction, ONE strategy (the seesaw), trade-by-trade + the PER-POST pace. Shows Sir why
it loses: the per-post center is accurate LATE (~1/tweet) but garbage EARLY (swings 30-75/tweet)."""
import os
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
tr=pd.read_csv(f"{D}/one_auction_trades.csv"); tw=pd.read_csv(f"{D}/one_auction_tweets.csv")
mv=pd.to_numeric(tw['per_post_move'],errors='coerce')
early=mv[tw.hrs_to_close>24].abs(); late=mv[tw.hrs_to_close<=6].abs()
e_mean=round(early.mean(),1); e_max=round(early.max(),1); l_mean=round(late.mean(),1)
nb=int((tr.action=='BUY').sum()); ns=int((tr.action=='SELL').sum())
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)
summary=[
["ONE AUCTION, ONE STRATEGY - the seesaw, trade by trade (april-16 -> april-18, winner 65-89, actual count 77)"],
[""],
["THE STRATEGY (one, simple)","Every POST, recompute our center (pace) and turn it into a FAIR price for each bracket. Then tick by tick: BUY a bracket when the market is cheaper than our fair by >= 2c, SELL it when the market is richer than our fair by >= 2c. Hold whatever is left to resolution. That is the whole thing."],
["THE TRADES",f"{len(tr)} total ({nb} buys, {ns} sells) - the hundreds of back-and-forth you expected. See the 'Every Trade' tab."],
[""],
["BUT HERE IS YOUR #1, EXACTLY","You said: 'I don't need the final pace accurate, I need the pace PER POST accurate.' It is NOT. Look at the 'Per-Post Pace' tab:"],
[f"  EARLY (>24h left)",f"one tweet swings our center by {e_mean} counts on average, up to {e_max}. Tweet 11 moved it -75 (from 152 to 77). That is nonsense - one tweet cannot change the true outlook by 75."],
[f"  LATE (<6h left)",f"one tweet moves our center ~{l_mean} counts. THAT is accurate (one more tweet ~= +1 to the final)."],
["WHY IT SWINGS EARLY","With only a few tweets and ~45h left, we extrapolate the current rate across the whole window, so one tweet massively changes the extrapolation. The locked pace model does this by design."],
[""],
["WHY THE STRATEGY LOSES (P&L -$1,348)","Because we TRADE on the garbage early center. At hour 45 our center said 152, so our fair said 140-164 was worth 0.80 and we bought it at 0.05 (looks like a huge edge). But the real count was 77 - those high brackets were losers. We loaded $900 of them and held to zero. The mechanic is fine; the per-post pace feeding it is wrong early."],
[""],
["THE FIX (keeps the locked pace model, does NOT change the center)","Make our CONFIDENCE honest. Right now sigma ~10 the whole auction, so early we act certain about a center that is swinging 75. Fix: sigma HUGE early (we genuinely don't know -> fair prices go flat -> NO early trades), shrinking to ~1-2 near the close (where the per-post pace IS accurate). We keep the locked center; we just stop believing it when it is uncertain. That kills the bad early trades and concentrates the seesaw in the last ~12-24h where it is real."],
["WANT VAI TO APPLY IT?","One knob (sigma), same one auction, re-run, and you will see the trades collapse to the late window where the pace is trustworthy. Then we judge the real edge."],
[""],
["TABS","'Per-Post Pace' = every tweet, center before/after, and the per-post move (the #1 thing). 'Every Trade' = all "+str(len(tr))+" trades with our center, our fair, the market price, and the edge we acted on."],
]
def rows(df,cols):
    out=[cols]
    for _,r in df.iterrows(): out.append([('' if pd.isna(r[c]) else r[c]) for c in cols])
    return out
twcols=['tweet_no','et','hrs_to_close','count_so_far','center_before','center_after','per_post_move','sigma']
tw_t=rows(tw[twcols],twcols)
trcols=['et','hrs_to_close','action','bracket','price','our_fair','edge','our_center','shares','inv_$']
tr_t=rows(tr[trcols],trcols)
TABS=[("Read me first",summary,0),("Per-Post Pace",tw_t,1),("Every Trade",tr_t,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'ONE auction, ONE strategy - seesaw trade-by-trade + per-post pace'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
sid=idm['Read me first']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':240},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':900},'fields':'pixelSize'}})
for nm,nc in [('Per-Post Pace',8),('Every Trade',10)]:
    reqs.append({'repeatCell':{'range':{'sheetId':idm[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
# highlight big per-post moves (|move|>10) on the pace tab, col 6
sid=idm['Per-Post Pace']
for c,v in [("NUMBER_GREATER","10"),("NUMBER_LESS","-10")]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tw_t),'startColumnIndex':6,'endColumnIndex':7}],'booleanRule':{'condition':{'type':c,'values':[{'userEnteredValue':v}]},'format':{'backgroundColor':{'red':0.98,'green':0.80,'blue':0.80}}}},'index':0}})
# buy/sell colors on trades, col 2
sid=idm['Every Trade']
for val,color in [("BUY",{'red':0.83,'green':0.94,'blue':0.83}),("SELL",{'red':0.99,'green':0.90,'blue':0.80})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tr_t),'startColumnIndex':2,'endColumnIndex':3}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
