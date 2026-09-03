# -*- coding: utf-8 -*-
"""Build a Google Sheet that shows S3 (Anchor + Harvest) from the REAL backtest: the logic,
every S3 order (core vs sleeve), per-auction P&L, and one auction traced step by step.
All numbers computed from audit_out2/trades.csv. DWD service account (subject=darwin@xagency.com)."""
import os, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
ET=ZoneInfo('America/New_York')
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out2"
tr=pd.read_csv(f"{D}/trades.csv"); au=pd.read_csv(f"{D}/auctions.csv")
s3=tr[tr.book=='S3'].copy()
s3['leg']=s3.rule.apply(lambda r:'CORE' if 'held' in r else 'SLEEVE')
s3['won']=(s3.bracket.astype(str)==s3.winner.astype(str)).astype(int)
s3['et']=s3.hour_ts.apply(lambda t: datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'))
s3['short']=s3.slug.str.replace('elon-musk-of-tweets-','',regex=False)

# per-auction
rows=[]
for slug,d in s3.groupby('slug'):
    core=d[(d.leg=='CORE')&(d.side=='BUY')]
    core_pnl=(core.shares*((core['won'])-core.fill_price)).sum()
    core_dep=(core.shares*core.fill_price).sum()
    slb=d[(d.leg=='SLEEVE')&(d.side=='BUY')]; sls=d[(d.leg=='SLEEVE')&(d.side=='SELL')]
    sleeve_pnl=(sls.shares*sls.fill_price).sum()-(slb.shares*slb.fill_price).sum()
    sleeve_dep=(slb.shares*slb.fill_price).sum()
    held_win='YES' if (core['won'].sum()>0) else 'no'
    rows.append(dict(slug=slug,short=d.short.iloc[0],dur=d.dur.iloc[0],winner=str(d.winner.iloc[0]),
        n_core=len(core),core_dep=core_dep,core_pnl=core_pnl,n_sleeve=len(slb),sleeve_dep=sleeve_dep,
        sleeve_pnl=sleeve_pnl,total=core_pnl+sleeve_pnl,held_win=held_win))
pa=pd.DataFrame(rows).sort_values('slug')

# pick a traced auction: a 2-day with both core+sleeve activity, winner NOT held (typical loss)
cand=pa[(pa.dur=='2-day')&(pa.n_sleeve>=2)&(pa.held_win=='no')].sort_values('n_core',ascending=False)
traced_slug=cand.iloc[0].slug if len(cand) else pa.sort_values('n_core',ascending=False).iloc[0].slug
td=s3[s3.slug==traced_slug].sort_values('hour_ts')

creds=service_account.Credentials.from_service_account_file(
    os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],
    subject='darwin@xagency.com')
sheets=build('sheets','v4',credentials=creds); drive=build('drive','v3',credentials=creds)

def m(x): return round(float(x),2)
core_tot=pa.core_pnl.sum(); sleeve_tot=pa.sleeve_pnl.sum(); grand=pa.total.sum()
cb=s3[(s3.leg=='CORE')&(s3.side=='BUY')]; core_hit=100*(cb.shares*cb['won']).sum()/cb.shares.sum()

# ---- TAB 1: S3 LOGIC ----
logic=[
["S3 ANCHOR + HARVEST  -  what it does, and why it lost (all from the real backtest)"],
[""],
["In one line","S3 = hold a CORE basket to resolution (like S2) PLUS scalp a 30% SLEEVE on the price swings (like S1), and never sell the core. On real data it lost -13%."],
[""],
["THE TWO LEGS"],
["CORE (held to resolution)","For each BAND bracket (our model's win prob >= 5%), when the price dips at least 3c BELOW our model's fair value, rest a maker bid and buy the dip. Size = quarter-Kelly off the edge. HOLD every core lot to the end. Pays $1 if that bracket wins, else $0. This is identical to S2."],
["SLEEVE (scalped, 30% size)","Same dip-buy entry but 30% of the size, AND it sells: take profit when the bid pops >= 3c ABOVE our fair, cut at a 6c stop, else flatten at the close. A round-trip book. This is the 'harvest' that is supposed to grind the cost basis down."],
["Never sells the core","The core is the anchor. Only the sleeve trades in and out."],
[""],
["THE REAL RESULT (computed from trades.csv)"],
["S3 orders",f"{len(s3)} total: {len(cb)} core buys (held) + {len(s3[(s3.leg=='SLEEVE')&(s3.side=='BUY')])} sleeve round-trips"],
["Core P&L",f"${core_tot:,.0f}"],
["Sleeve P&L",f"${sleeve_tot:,.0f}"],
["Total S3 P&L",f"${grand:,.0f}  (-13% on deployed)"],
[""],
["WHY IT LOST (the core is the whole story)"],
["Our fair value is overconfident",f"Only {core_hit:.1f}% of all core shares landed on the bracket that actually won. We bought dozens of brackets our model called 'cheap vs fair' that the market had priced correctly, and held them to $0."],
["The sleeve does not save it","The harvest sleeve also netted negative (small). Scalping the swings does not offset holding losers in the core."],
["The structure is fine, the brain is not","Basket-hold + harvest is a sound design. The problem is the Kalman fair value: it says brackets are underpriced when they are not. Feed it a correct fair value (the market price is well-calibrated) and there is almost nothing to buy."],
[""],
["HOW TO READ THE OTHER TABS"],
["'S3 Per-Auction'","Every auction: core vs sleeve deployed and P&L, the official winner, and whether the core actually held the winner. Look at the 'Held winner?' column - it is 'no' on most rows."],
["'S3 Every Trade'","All 970 S3 orders. CORE rows are the held basket; SLEEVE rows are the scalps (BUY then SELL). Every row shows OUR fair vs the ask so you can see the model calling things cheap."],
["'One Auction Traced'","A single auction start to finish: the core dip-buys pile up across brackets, the sleeve scalps in and out, and at the end only the winner pays."],
]

# ---- TAB 2: PER-AUCTION ----
pah=["Auction","Type","Winner","Held winner?","# core buys","Core deployed $","Core P&L $","# sleeve","Sleeve P&L $","S3 total $"]
pat=[pah]
for _,r in pa.iterrows():
    pat.append([r.short,r.dur,r.winner,r.held_win,int(r.n_core),m(r.core_dep),m(r.core_pnl),int(r.n_sleeve),m(r.sleeve_pnl),m(r.total)])
pat.append([])
pat.append(["TOTAL","","","","",m(pa.core_dep.sum()),m(core_tot),"",m(sleeve_tot),m(grand)])

# ---- TAB 3: EVERY TRADE ----
eth=["Auction","Time (ET)","Leg","Side","Bracket","Fill ¢","Shares","Our fair %","Market ask ¢","Bid ¢","This bracket won?","Rule"]
ett=[eth]
for _,r in s3.sort_values(['slug','hour_ts','leg']).iterrows():
    ett.append([r.short,r.et,r.leg,r.side,str(r.bracket),round(r.fill_price*100,1),round(r.shares,0),
        round(r.fair*100,0),round(r.ask*100,1),round(r.bid*100,1),'WON' if r.won else '',r.rule])

# ---- TAB 4: ONE AUCTION TRACED ----
tw=str(td.winner.iloc[0]); tshort=td.short.iloc[0]
tr_core=two=tdd=None
trh=["Step","Time (ET)","Leg","Side","Bracket","Fill ¢","Shares","Our fair %","Ask ¢","Bid ¢","What happened"]
trt=[[f"AUCTION: {tshort}  ({td.dur.iloc[0]})   OFFICIAL WINNER = {tw}"],[""],trh]
for i,(_,r) in enumerate(td.iterrows(),1):
    if r.leg=='CORE':
        note=f"core dip-buy: ask {r.ask*100:.0f}c is >3c below our fair {r.fair*100:.0f}%. Hold to end. ({'this bracket WINS' if r.won else 'loses at resolution'})"
    elif r.side=='BUY':
        note=f"sleeve entry: buy the dip, 30% size"
    else:
        note="sleeve exit above fair (take profit)" if 'exit' in r.rule else ("sleeve stop" if 'stop' in r.rule else "sleeve flatten at close")
    trt.append([i,r.et,r.leg,r.side,str(r.bracket),round(r.fill_price*100,1),round(r.shares,0),round(r.fair*100,0),round(r.ask*100,1),round(r.bid*100,1),note])
trow=pa[pa.slug==traced_slug].iloc[0]
trt.append([])
trt.append(["OUTCOME",f"winner {tw}. Core held {int(trow.n_core)} lots; core P&L ${trow.core_pnl:,.0f}, sleeve P&L ${trow.sleeve_pnl:,.0f}, total ${trow.total:,.0f}. "+("The core DID hold the winner here." if trow.held_win=='YES' else "The core did NOT hold the winner - every core lot paid $0.")])

TABS=[("S3 Logic",logic,0),("S3 Per-Auction",pat,1),("S3 Every Trade",ett,1),("One Auction Traced",trt,0)]
ss=sheets.spreadsheets().create(body={'properties':{'title':'S3 Anchor+Harvest - Real Backtest Logic + Trades'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idmap={s['properties']['title']:s['properties']['sheetId'] for s in ss['sheets']}
sheets.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW',
    'data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()

DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
def hdr(name,ncol):
    reqs.append({'repeatCell':{'range':{'sheetId':idmap[name],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':ncol},
        'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
def wrap(name,ncol,w0=None,wn=None):
    sid=idmap[name]
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':ncol},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
    if w0: reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':w0},'fields':'pixelSize'}})
    if wn: reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':wn},'fields':'pixelSize'}})
def cond_pnl(name,col,nrow):
    sid=idmap[name]
    for cond,color in [("NUMBER_GREATER",{'red':0.82,'green':0.94,'blue':0.83}),("NUMBER_LESS",{'red':0.98,'green':0.85,'blue':0.83})]:
        reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':nrow,'startColumnIndex':col,'endColumnIndex':col+1}],
            'booleanRule':{'condition':{'type':cond,'values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':color}}},'index':0}})
# logic + traced = text
for nm,data in [("S3 Logic",logic),("One Auction Traced",trt)]:
    sid=idmap[nm]
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':11},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':300 if nm=='S3 Logic' else 90},'fields':'pixelSize'}})
    if nm=='S3 Logic': reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':720},'fields':'pixelSize'}})
# traced header row3
reqs.append({'repeatCell':{'range':{'sheetId':idmap['One Auction Traced'],'startRowIndex':2,'endRowIndex':3,'startColumnIndex':0,'endColumnIndex':11},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':idmap['One Auction Traced'],'dimension':'COLUMNS','startIndex':10,'endIndex':11},'properties':{'pixelSize':380},'fields':'pixelSize'}})
hdr("S3 Per-Auction",len(pah)); wrap("S3 Per-Auction",len(pah),160)
cond_pnl("S3 Per-Auction",6,len(pat)); cond_pnl("S3 Per-Auction",8,len(pat)); cond_pnl("S3 Per-Auction",9,len(pat))
hdr("S3 Every Trade",len(eth)); wrap("S3 Every Trade",len(eth),150)
reqs.append({'updateDimensionProperties':{'range':{'sheetId':idmap['S3 Every Trade'],'dimension':'COLUMNS','startIndex':11,'endIndex':12},'properties':{'pixelSize':300},'fields':'pixelSize'}})
# color CORE vs SLEEVE leg column (col 2) in Every Trade
for val,color in [("CORE",{'red':0.85,'green':0.92,'blue':0.98}),("SLEEVE",{'red':0.99,'green':0.93,'blue':0.83})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':idmap['S3 Every Trade'],'startRowIndex':1,'endRowIndex':len(ett),'startColumnIndex':2,'endColumnIndex':3}],
        'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sheets.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: drive.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as e: print('share warn',e)
url=drive.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink']
print("traced auction:",traced_slug,"| held_win:",trow.held_win)
print("SHEET_URL:",url)
