# -*- coding: utf-8 -*-
"""Sheet: one FULL auction under the LOCKED pace model (Ensemble+CAP1.5) running Sir's divergence
strategy. Signals only. Shows every trade, whether that bracket actually won, and the full
bar-by-bar pace timeline (our pace vs market pace vs the true final)."""
import os
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
td=pd.read_csv(f"{D}/signals_locked.csv"); tl=pd.read_csv(f"{D}/timeline_locked.csv")
FINAL=int(tl.true_final.iloc[0]); WIN=str(tl.true_winner.iloc[0])
buys=td[td.action=='BUY']; hit=int((buys.was_winner=='WINNER').sum())
tl['our_err']=(tl['our_pace(locked)']-FINAL).abs(); tl['mkt_err']=(tl['market_pace(revpace)']-FINAL).abs()
def seg(m):
    s=tl[m]; return (s.our_err.mean(), s.mkt_err.mean(), 100*(s.our_err<s.mkt_err).mean(), len(s))
e1=seg(tl.hrs_in<=12); e2=seg((tl.hrs_in>12)&(tl.hrs_in<=36)); e3=seg(tl.hrs_in>36)

creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)

info=[
["YOUR DIVERGENCE STRATEGY, ONE FULL AUCTION, LOCKED PACE MODEL (signals only, no fills)"],
[""],
["Auction","elon-musk-of-tweets-may-14-may-16. He finished at %d tweets. Official winner: %s."%(FINAL,WIN)],
[""],
["LOCKED PACE MODEL","Ensemble+CAP1.5 (chosen by the 144-auction walk-forward leaderboard)"],
["1. Kalman leg","o + (baseline_rate + K*(live_rate - baseline_rate)) x hours_left"],
["2. AccrualCurve leg","posts_so_far / (typical % of the window done by this hour)"],
["3. Blend","time-weighted: trust Kalman early, AccrualCurve late"],
["4. RATE CAP","the go-forward rate cannot exceed 1.5x his historical baseline. This is what stops the runaway burst projections."],
["Did the cap work?","YES. Our pace now ranges 69-140 across the auction. Before: raw AccrualCurve 110-311, uncapped ensemble 66-185. No more 172 nonsense."],
[""],
["YOUR STRATEGY (what fires a trade)"],
["Our pace","the locked model's projected final count."],
["Market pace","reverse-pace: sum(bracket-center x live price). What the crowd's prices imply."],
["Edge","divergence = our pace - market pace. Enter when |divergence| >= 5. Rotate when our pace moves to a new bracket. Exit when it converges (<=2). In and out."],
[""],
["THE TEST RESULT (no money simulated, just: was the signal right?)"],
["Trades fired","%d orders (%d BUY, %d SELL)"%(len(td),len(buys),len(td)-len(buys))],
["BUYs on the winning bracket","%d of %d (%.0f%%). The other %d were all HIGHER brackets, bought while our pace was still over-projecting."%(hit,len(buys),100*hit/max(len(buys),1),len(buys)-hit)],
[""],
["WHOSE PACE WAS ACTUALLY CLOSER TO THE TRUTH (%d)?"%FINAL],
["First 12 hours","our avg error %.1f  vs  market %.1f   -> the market is ~5x better. We are closer on only %.0f%% of bars."%(e1[0],e1[1],e1[2])],
["Hours 12 to 36","our avg error %.1f  vs  market %.1f   -> market still better. We are closer on %.0f%% of bars."%(e2[0],e2[1],e2[2])],
["Last 12 hours","our avg error %.1f  vs  market %.1f   -> DEAD EVEN. We are closer on %.0f%% of bars (a coin flip)."%(e3[0],e3[1],e3[2])],
[""],
["WHAT THIS MEANS (honest, one auction)","Early, the divergence is OUR error, not the market's mispricing: the market's reverse-pace is far closer to the truth than our model. By the time our model is accurate (last 12h), we AGREE with the market, so the divergence collapses and there is nothing left to trade. On this auction the strategy has no edge. That is one auction, not a verdict, but it is the same pattern we have seen every time."],
["Tabs","'Every Trade' = all %d orders, with whether that bracket actually won. 'Full Auction Timeline' = every 10-min bar: our pace, the market's pace, the divergence, and what the strategy did."%len(td)],
]
def rows_from(df,cols,hdr):
    out=[hdr]
    for _,r in df.iterrows(): out.append([r[c] if pd.notna(r[c]) else '' for c in cols])
    return out
sig=rows_from(td,['et','action','bracket','was_winner','tweets_so_far','our_pace','market_pace','divergence','bracket_price','why'],
    ['Time (ET)','Action','Bracket','Did it win?','Tweets so far','Our pace','Market pace','Divergence','Bracket price','Why it fired'])
tlx=tl.copy(); tlx['our_closer']=np.where(tlx.our_err<tlx.mkt_err,'ours','market')
tlr=rows_from(tlx,['et','hrs_in','tweets_so_far','our_pace(locked)','market_pace(revpace)','divergence','pace_points_to','holding','action','our_closer'],
    ['Time (ET)','Hrs in','Tweets so far','Our pace (locked)','Market pace','Divergence','Pace points to','Holding','Action','Closer to truth'])

TABS=[("Locked Model + Result",info,0),("Every Trade",sig,1),("Full Auction Timeline",tlr,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'Divergence Strategy - ONE FULL AUCTION (locked Ensemble+CAP1.5)'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
sid=idm['Locked Model + Result']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':190},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':800},'fields':'pixelSize'}})
for nm,nc in [('Every Trade',10),('Full Auction Timeline',10)]:
    reqs.append({'repeatCell':{'range':{'sheetId':idm[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
sid=idm['Every Trade']
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':9,'endIndex':10},'properties':{'pixelSize':320},'fields':'pixelSize'}})
for val,color in [("WINNER",{'red':0.82,'green':0.94,'blue':0.83}),("loser",{'red':0.98,'green':0.87,'blue':0.85})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(sig),'startColumnIndex':3,'endColumnIndex':4}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sid=idm['Full Auction Timeline']
for val,color in [("ours",{'red':0.82,'green':0.94,'blue':0.83}),("market",{'red':0.98,'green':0.87,'blue':0.85})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tlr),'startColumnIndex':9,'endColumnIndex':10}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
print(f"trades {len(td)} | timeline bars {len(tl)} | BUY-on-winner {hit}/{len(buys)}")
