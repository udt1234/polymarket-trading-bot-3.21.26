# -*- coding: utf-8 -*-
"""Sheet: Sir's divergence strategy, 22 two-day auctions, locked Ens+CAP1.5, conservative maker fills,
official winners. Primary = gate hour 24, plus the gate comparison (accuracy vs price-edge crossover)."""
import os, math
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
G={g:(pd.read_csv(f"{D}/strategy_trades_gate{g}.csv"),pd.read_csv(f"{D}/strategy_auctions_gate{g}.csv")) for g in (12,24,36)}
def stats(g):
    tr,au=G[g]; t=au[au.buys>0]; buys=tr[tr.action=='BUY']
    cap=au.deployed.sum(); pnl=au.pnl.sum()
    m=t.roi_pct.mean(); sd=t.roi_pct.std(); se=sd/math.sqrt(len(t)) if len(t)>1 else np.nan
    hit=100*(buys.won_at_resolution=='WINNER').mean() if len(buys) else np.nan
    return dict(gate=f"hour {g}+",buys=len(buys),deployed=round(cap),pnl=round(pnl),
        roi=round(100*pnl/cap,1) if cap else 0,prof=f"{(t.pnl>0).sum()}/{len(t)}",
        mean=round(m,1),se=round(se,1),sig=("significant" if abs(m)>2*se else "inside noise"),winner_hit=round(hit))
cmp=pd.DataFrame([stats(g) for g in (12,24,36)])
tr,au=G[24]; buys=tr[tr.action=='BUY']; t=au[au.buys>0]
cap=au.deployed.sum(); pnl=au.pnl.sum(); m=t.roi_pct.mean(); se=t.roi_pct.std()/math.sqrt(len(t))
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)
info=[
["YOUR DIVERGENCE STRATEGY - 22 two-day auctions, real order book, official winners"],
[""],
["THE BUILD (everything we agreed, nothing else)"],
["Our center","LOCKED pace model Ens+CAP1.5: Kalman early + AccrualCurve late, blended, go-forward rate capped at 1.5x baseline."],
["Market's opinion","Reverse-pace (market implied count). The OTHER OPINION only. It is NOT our fair value."],
["Edge","Divergence = our center - market center. Enter when |divergence| >= 5. Rotate when our center moves to a new bracket. Exit on convergence (<=2) or a 6c stop."],
["Pricing","The MARKET's prices, never our probabilities. Our probabilities are overconfident (30% claimed, 7% real). Our edge is the CENTER, not the SPREAD."],
["Gate","Hour 24+. S0 proved we LOSE to the market in the first 12h (37% of bars) and WIN after."],
["Fills","Conservative MAKER only. A buy fills only if the bar's LOW ask crosses down to our resting bid. A sell fills only if the bar's HIGH bid crosses up to our resting ask. Haircut on every exit. Depth-capped."],
["Winners","Official Gamma resolution. Never our own tweet count."],
[""],
["THE RESULT (gate hour 24)"],
["Orders",f"{len(buys)} BUY, {len(tr[tr.action=='SELL'])} SELL. Every position closed."],
["Capital deployed",f"${cap:,.0f}"],
["P&L",f"${pnl:+,.0f}   ->   ROI {100*pnl/cap:+.1f}%"],
["Profitable auctions",f"{(t.pnl>0).sum()} of {len(t)}"],
["Per-auction ROI",f"mean {m:+.1f}%, standard error {se:.1f}%   ->   NOT statistically significant. With 20 auctions this sits inside the noise."],
["BUYs on the eventual winner",f"{(buys.won_at_resolution=='WINNER').sum()} of {len(buys)} ({100*(buys.won_at_resolution=='WINNER').mean():.0f}%)"],
[""],
["WHAT CHANGED"],
["Before","The earlier backtest (wrong model, no gate, our own overconfident probabilities as fair value) lost -12% to -22%."],
["Now","Same market, same fill model, same official winners. Fixing the model, adding the gate, and pricing off the market takes it from -12% to positive. The diagnosis was right."],
["Be honest","+3.7% on 22 auctions is not an edge yet. It is a strategy that has stopped bleeding. It is not yet a strategy that makes money."],
[""],
["THE NON-OBVIOUS FINDING (see the Gate Comparison tab)"],
["The crossover","Our FORECAST gets more accurate as the auction ends: at hour 36+ we buy the eventual winner 71% of the time, versus 53% at hour 12. But hour 36+ LOSES money (-4.4%)."],
["Why","By then the market has already priced it. The winning bracket trades at 0.90+. Being right is worthless if the price already reflects it."],
["So","Our accuracy edge and our price edge move in OPPOSITE directions. They cross around hour 24. That is why the gate belongs there and not at the finish line."],
[""],
["WHAT IS NOT IN THESE NUMBERS"],
["Maker rebates","~10-12 bps per fill on 138 fills, plus LP rewards. Not counted. Adds a small positive."],
["Queue risk","Our fill model assumes we are at the front of the queue whenever the price touches our bid. Real fills will be worse. Next thing to measure."],
]
def rows(df,cols,hdr):
    out=[hdr]
    for _,r in df.iterrows(): out.append([r[c] if pd.notna(r[c]) else '' for c in cols])
    return out
cmp_t=rows(cmp,['gate','buys','deployed','pnl','roi','prof','mean','se','sig','winner_hit'],
    ['Gate','BUY orders','Deployed $','P&L $','ROI %','Profitable auctions','Per-auction mean ROI %','Std err %','Significant?','BUYs on winner %'])
au_t=rows(au,['slug','winner','final','buys','deployed','pnl','roi_pct'],
    ['Auction','Official winner','Final count','BUY orders','Deployed $','P&L $','ROI %'])
tr_t=rows(tr,['slug','et','hrs_in','action','bracket','won_at_resolution','fill_price','shares','tweets','our_center','market_center','divergence','why'],
    ['Auction','Time (ET)','Hrs in','Action','Bracket','Did it win?','Fill price','Shares','Tweets so far','Our center','Market center','Divergence','Why it fired'])
TABS=[("Strategy + Result",info,0),("Gate Comparison",cmp_t,1),("Per-Auction",au_t,1),("Every Trade",tr_t,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'Divergence Strategy - 22 auctions, locked model, maker fills'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
sid=idm['Strategy + Result']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':200},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':820},'fields':'pixelSize'}})
for nm,nc in [('Gate Comparison',10),('Per-Auction',7),('Every Trade',13)]:
    reqs.append({'repeatCell':{'range':{'sheetId':idm[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
def cond(nm,col,nrow):
    for c,color in [("NUMBER_GREATER",{'red':0.82,'green':0.94,'blue':0.83}),("NUMBER_LESS",{'red':0.98,'green':0.87,'blue':0.85})]:
        reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':idm[nm],'startRowIndex':1,'endRowIndex':nrow,'startColumnIndex':col,'endColumnIndex':col+1}],'booleanRule':{'condition':{'type':c,'values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':color}}},'index':0}})
cond('Per-Auction',5,len(au_t)); cond('Per-Auction',6,len(au_t)); cond('Gate Comparison',3,len(cmp_t)); cond('Gate Comparison',4,len(cmp_t))
sid=idm['Every Trade']
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':12,'endIndex':13},'properties':{'pixelSize':300},'fields':'pixelSize'}})
for val,color in [("BUY",{'red':0.85,'green':0.94,'blue':0.85}),("SELL",{'red':0.99,'green':0.92,'blue':0.83})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tr_t),'startColumnIndex':3,'endColumnIndex':4}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
for val,color in [("WINNER",{'red':0.82,'green':0.94,'blue':0.83}),("loser",{'red':0.98,'green':0.88,'blue':0.86})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(tr_t),'startColumnIndex':5,'endColumnIndex':6}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
print(cmp.to_string(index=False))
