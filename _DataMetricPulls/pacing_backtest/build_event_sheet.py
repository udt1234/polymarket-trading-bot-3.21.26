# -*- coding: utf-8 -*-
"""Sheet: ONE auction (april-16-april-18), EVENT-DRIVEN (every tweet + every price tick), locked model."""
import os
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
tr=pd.read_csv(f"{D}/event_trades.csv"); tl=pd.read_csv(f"{D}/event_timeline.csv")
buys=tr[tr.action=='BUY']; pnl=0.0
# reconstruct round-trip pnl for display
pnl=round(sum((tr.iloc[i+1].fill-tr.iloc[i].fill)*tr.iloc[i].shares for i in range(0,len(tr)-1,2)),2) if len(tr)>=2 else 0
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)
info=[
["ONE AUCTION, EVENT-DRIVEN - april-16-april-18 (winner 65-89, he finished at 77)"],
[""],
["WHAT I FIXED","Every earlier backtest ran on 10-MINUTE BARS. This one processes the real event stream: all 77 tweets and all 798,624 price ticks in true time order, exactly like the live bot. Our center recomputes on every tweet; the market's center updates on every tick; the divergence is evaluated at every event."],
[""],
["THE RESULT","6 orders, 3 round-trips. Deployed $324. P&L about -$85 (-26%). 1 of 3 buys was on the eventual winner. This is ONE auction, so the P&L is not the point. WHY it lost is the point, and there are two real reasons."],
[""],
["FINDING 1: MAKER ORDERS ON A DIRECTIONAL BET ARE ADVERSELY SELECTED"],
["The problem","We rest a bid on the bracket we think is UNDER-priced (should go up). But a resting bid only fills when a seller crosses DOWN to it, i.e. when the price is FALLING. Look at trade 1: our bid filled at 0.60 as 65-89 was dropping, and it kept dropping, so we sold at 0.57. We caught a falling knife."],
["Why it matters","This is structural, not bad luck. A maker who wants a bracket to rise gets filled precisely when it falls. Directional conviction and maker-only fills fight each other. This is the single biggest reason the divergence-as-a-maker-strategy struggles."],
[""],
["FINDING 2: OUR CENTER OVER-PROJECTED THIS AUCTION"],
["What happened","From hour 24 to 38 our center sat at 90-98 while he was actually heading for 77. So we kept buying 90-114 (a loser) and stopping out. Our center only converged to 77 (pointing at the real winner 65-89) at hour 46, far too late to trade."],
["The market was closer","The market's center held ~84 the whole time. On THIS auction the market beat us. Our leaderboard win (56.6% of bars) is an average; this is one of the 43% we lose. The market is closer more often than not, but not always."],
[""],
["FINDING 3: YOUR INTUITION ABOUT SWINGS - PARTLY RIGHT"],
["Early swings are huge","Our center swung from 141 (hour 2) to 76 (hour 8) to 80 (hour 23), driven by his bursts and quiet stretches. See the timeline. These are pre-gate, so they do not trade."],
["Late it is STABLE","In the last 12 hours the center moves ~1 per tweet (96 -> 95 -> 96 -> 98). Near the end it is calm, not swinging. So the wild moves are early, the stable ones are late. The gate at hour 24 sits right where it settles down."],
[""],
["THE CONCLUSION THIS POINTS TO","The directional divergence strategy, forced to be a maker, is adversely selected (Finding 1). The MAKER COMPLEMENT-PAIR ARB you do manually does NOT have this problem: you rest a YES bid and a NO bid, and you profit from the spread no matter which way the price moves. It is non-directional, so it is not adversely selected. That is the maker-friendly play, and it is why your manual instinct is right and my divergence bot keeps fighting the fill mechanics."],
["Tabs","'Every Tweet' = our center recomputed at each of the 73 tweets (with the per-tweet change), the market's center, the divergence, and what we held. 'Every Trade' = all 6 fills with why."],
]
def rows(df,cols,hdr):
    out=[hdr]
    for _,r in df.iterrows(): out.append([r[c] if pd.notna(r[c]) else '' for c in cols])
    return out
tl_t=rows(tl,['et','hrs_in','tweet_no','our_center','d_center_per_tweet','market_center','divergence','our_bracket','holding'],
    ['Time (ET)','Hrs in','Tweet #','Our center','Change vs last tweet','Market center','Divergence','Our bracket','Holding'])
tr_t=rows(tr,['et','hrs','action','bracket','won','fill','shares','tweets','our','mkt','div','why'],
    ['Time (ET)','Hrs in','Action','Bracket','Did it win?','Fill price','Shares','Tweets','Our center','Market center','Divergence','Why'])
TABS=[("Event-Driven Result",info,0),("Every Tweet",tl_t,1),("Every Trade",tr_t,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'ONE auction, EVENT-DRIVEN (per tweet + per tick) - april-16-18'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
sid=idm['Event-Driven Result']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':210},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':830},'fields':'pixelSize'}})
for nm,nc in [('Every Tweet',9),('Every Trade',12)]:
    reqs.append({'repeatCell':{'range':{'sheetId':idm[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
# highlight big center swings in Every Tweet (col 4 = change)
sid=idm['Every Tweet']
for c,color in [("NUMBER_GREATER",{'red':0.98,'green':0.85,'blue':0.7}),("NUMBER_LESS",{'red':0.98,'green':0.85,'blue':0.7})]:
    v='10' if 'GREATER' in c else '-10'
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tl_t),'startColumnIndex':4,'endColumnIndex':5}],'booleanRule':{'condition':{'type':c,'values':[{'userEnteredValue':v}]},'format':{'backgroundColor':color}}},'index':0}})
sid=idm['Every Trade']
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':11,'endIndex':12},'properties':{'pixelSize':320},'fields':'pixelSize'}})
for val,color in [("BUY",{'red':0.85,'green':0.94,'blue':0.85}),("SELL",{'red':0.99,'green':0.92,'blue':0.83})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tr_t),'startColumnIndex':2,'endColumnIndex':3}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
for val,color in [("WINNER",{'red':0.82,'green':0.94,'blue':0.83}),("loser",{'red':0.98,'green':0.88,'blue':0.86})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tr_t),'startColumnIndex':4,'endColumnIndex':5}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
