# -*- coding: utf-8 -*-
"""Sheet: depth-capped SPEED STRATEGY on the entire auction, confirmed on 2 auctions + trade-by-trade."""
import os, glob
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
grids=pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{D}/depth_speed_grid_*.csv"))],ignore_index=True)
def loadtr(tag):
    f=f"{D}/depth_speed_trades_{tag}.csv"
    t=pd.read_csv(f); t.insert(0,'auction',tag); return t
tr27=loadtr('june-27-june-29'); tr25=loadtr('june-25-june-27')
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)
verdict=[
["SPEED STRATEGY - DEPTH-CAPPED, WHOLE AUCTION, CONFIRMED ON 2 AUCTIONS"],
[""],
["THE STRATEGY","On every tweet, at T+latency BUY the +1 (next-higher) bracket and sell it after a hold of 3-10 min. This time fills WALK THE REAL ORDER BOOK (recorder full L2): buy up the ask ladder, sell down the bid ladder, priced so a stale snapshot can't hand us a pre-jump price. This is the honest test the top-of-book $50 version could not give."],
[""],
["THE VERDICT","DEAD at any tradeable size, on BOTH auctions. The +2.9c 'jump' is a MID-PRICE move you cannot capture with real money."],
["  june-27-29",  "$100 clip: -$352 / -$158 / +$136 (3/5/10min).  $250: -$1,974 to -$890.  $500: -$4,177+.  $1,000: -$12,955+."],
["  june-25-27 (confirm)","$100 clip: -$243 / -$214 / -$169 - ALL negative.  $250: -$1,399+.  $500: -$5,032+.  $1,000: -$15,425+."],
["The one 'positive'","$100 / 10min on june-27-29 = +$136 (45% win). The SAME cell on june-25-27 = -$169 (25% win). That is a one-auction coin-flip, not an edge."],
[""],
["WHY IT DIES","(1) Bracket books are THIN - a $250+ round-trip walks UP the asks going in and DOWN the bids coming out, moving the price against you both ways. (2) You must buy the +1 on EVERY tweet because you cannot know at T+250ms which ~67% are eventful; the non-events pay the round-trip cost for nothing. (3) 500ms latency is worse across the board."],
[""],
["WHERE THIS LEAVES ELON","Every capturable-at-size edge has now failed the same way: the 61% bracket-selection ceiling (seesaw) or real depth (speed). The measurable signals are real but not tradeable at size. Elon is efficient AND thin."],
["SO WHAT","If you still want a bot here: (a) semi-auto the seesaw (your bracket call + machine discipline), the only path that puts a human where the 61% model can't reach; or (b) point the reconstruction engine at less-efficient, deeper markets. The speed play is off the table unless a market with real depth shows the same tweet-reaction."],
[""],
["TABS","'Depth Grid' = total profit for both auctions across latency x clip x hold. 'Trades 27-29' and 'Trades 25-27' = every trade at the best 250ms cell, so you can see the round-trips."],
]
def rows(df,cols):
    out=[cols]
    for _,r in df.iterrows(): out.append([('' if pd.isna(r[c]) else r[c]) for c in cols])
    return out
gcols=['auction','latency_ms','clip_$','hold_min','total_profit_$','n_trades','win_rate_%','mean_$_per_trade']
g_t=rows(grids.sort_values(['auction','latency_ms','clip_$','hold_min'])[gcols],gcols)
tcols=['auction','et','bracket','buy_vwap','sell_vwap','shares','spent','pnl']
t27=rows(tr27[tcols],tcols); t25=rows(tr25[tcols],tcols)
TABS=[("Verdict",verdict,0),("Depth Grid",g_t,1),("Trades 27-29",t27,1),("Trades 25-27",t25,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'Speed Strategy - Depth-Capped, Whole Auction, 2-Auction Confirm'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
sid=idm['Verdict']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':200},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':900},'fields':'pixelSize'}})
for nm,nc in [('Depth Grid',8),('Trades 27-29',8),('Trades 25-27',8)]:
    reqs.append({'repeatCell':{'range':{'sheetId':idm[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
# red/green on total_profit (Depth Grid col 4) and pnl (Trades col 7)
for nm,ci,ln in [('Depth Grid',4,len(g_t)),('Trades 27-29',7,len(t27)),('Trades 25-27',7,len(t25))]:
    sid=idm[nm]
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':ln,'startColumnIndex':ci,'endColumnIndex':ci+1}],'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':{'red':0.98,'green':0.83,'blue':0.82}}}},'index':0}})
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':ln,'startColumnIndex':ci,'endColumnIndex':ci+1}],'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':{'red':0.83,'green':0.94,'blue':0.83}}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
