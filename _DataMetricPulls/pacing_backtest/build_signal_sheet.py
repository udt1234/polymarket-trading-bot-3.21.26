# -*- coding: utf-8 -*-
"""Push the one-auction divergence SIGNALS (AccrualCurve pace vs market reverse-pace, no fills)
to a Google Sheet so Sir can see every trade + the pace timeline behind them."""
import os
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
td=pd.read_csv(f"{D}/signals.csv"); tl=pd.read_csv(f"{D}/timeline.csv")
nb=int((td.action=='BUY').sum()); ns=int((td.action=='SELL').sum())

creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)

logic=[
["YOUR STRATEGY, SIGNALS ONLY (no fills, no P&L) - one auction: elon may-14-may-16"],
[""],
["What this is","The divergence scalp you described, run for real: our pace vs the market's pace, buy the edge, in and out. This shows the TRADE SIGNALS only. No fills, no money simulated (you said not to)."],
[""],
["THE MODEL (locked to what you told me)"],
["Our pace","AccrualCurve: our_count = tweets-so-far / (typical % of the window done by this hour), walk-forward. This is our shape-aware engine, NOT the naive linear Kalman."],
["Market pace","Reverse-pace: market_count = sum(bracket-center x that bracket's live price). What the crowd's prices imply for the final count."],
["The edge","Divergence = our_count - market_count. When they disagree, we act."],
[""],
["THE RULES (what fires a trade)"],
["Enter","When |divergence| >= 5, BUY the bracket our pace points to (the one our_count lands in)."],
["Rotate","If our pace moves to a different bracket, SELL the old one and BUY the new one."],
["Exit","When the divergence converges (|divergence| <= 2), SELL and go flat. In and out."],
[""],
["RESULT ON THIS AUCTION",f"{len(td)} signals ({nb} BUY, {ns} SELL). Official winner 65-89, he finished at 71 tweets."],
[""],
["HONEST NOTE (read before judging)","This is signals only, so there is no win/loss here. Two things you WILL see and should know: (1) the first few hours look wild (our pace prints 110-300) because the AccrualCurve divides by a tiny early share, so it over-reacts before the auction has data. (2) On this auction our AccrualCurve ran HIGH (it kept projecting ~110 while the market implied ~60 and he finished at 71), so most divergences here are our pace being too high, not the market being wrong. That is the calibration problem (prerequisite 7) showing up. It does not change that the strategy is now built correctly and firing your in/out divergence trades."],
["Tabs","'Trade Signals' = every BUY/SELL. 'Pace Timeline' = our pace vs market pace vs divergence at every 10-min bar, so you see exactly why each trade fired."],
]

def rows_from(df, cols, header):
    out=[header]
    for _,r in df.iterrows(): out.append([r[c] if pd.notna(r[c]) else '' for c in cols])
    return out
sig=rows_from(td,['et','action','bracket','tweets','our_count','mkt_count','divergence','price','reason'],
    ['Time (ET)','Action','Bracket','Tweets so far','Our pace (Accrual)','Market pace','Divergence','Bracket price','Why it fired'])
tlh=['Time (ET)','Hrs in','Tweets','Our pace (Accrual)','Market pace (revpace)','Divergence','Pace points to','Holding','Action']
tlr=rows_from(tl,['et','elapsed_h','tweets','our_count(Accrual)','mkt_count(revpace)','divergence','target_bracket','in_position','action'],tlh)

TABS=[("Strategy",logic,0),("Trade Signals",sig,1),("Pace Timeline",tlr,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'Divergence Strategy - Signals on one auction (may-14-16)'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idmap={s['properties']['title']:s['properties']['sheetId'] for s in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()

DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
def hdr(nm,nc): reqs.append({'repeatCell':{'range':{'sheetId':idmap[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
# strategy tab text
sid=idmap['Strategy']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':170},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':780},'fields':'pixelSize'}})
# signals: color BUY green SELL amber, widen reason
sid=idmap['Trade Signals']; hdr('Trade Signals',9)
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':8,'endIndex':9},'properties':{'pixelSize':340},'fields':'pixelSize'}})
for val,color in [("BUY",{'red':0.85,'green':0.94,'blue':0.85}),("SELL",{'red':0.99,'green':0.92,'blue':0.83})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(sig),'startColumnIndex':1,'endColumnIndex':2}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
hdr('Pace Timeline',9)
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
print(f"signals: {len(td)} | timeline bars: {len(tl)}")
