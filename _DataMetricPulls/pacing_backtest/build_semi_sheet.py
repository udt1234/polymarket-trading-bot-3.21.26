# -*- coding: utf-8 -*-
"""Sheet: SEMI-AUTO seesaw. Read-me + sensitivity, Config (bankroll/kelly/clip), Per-Post Pace (with
row-2 header descriptions), Every Trade (row-2 descriptions + EV/Kelly/Shares/Value as LIVE formulas)."""
import os
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
tr=pd.read_csv(f"{D}/semi_trades.csv"); tw=pd.read_csv(f"{D}/semi_tweets.csv")
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)

readme=[
["SEMI-AUTO SEESAW - you call the count, the bot runs the Kelly-sized fair-value execution"],
[""],
["THE IDEA","The only thing the model can't do is pick the bracket (it's stuck at 61%). YOU supply the count read; the bot does everything else per post: turns your read into a fair price per bracket (uncertainty shrinking as time runs out), then BUYS brackets the market has below our fair and SELLS them above it, Kelly-sized, disciplined, no emotion."],
[""],
["DOES IT WORK? (april-16 -> april-18, actual count 77)","YES - if your read is close. This is the whole game now:"],
["  your read 70","+$1,253"],["  your read 75 (shown)","+$846"],["  your read 80","+$846"],["  your read 85","+$526"],
["  your read 65","-$17"],["  your read 60 / 55","-$270"],["  your read 90","-$327"],["  your read 95","-$500"],
["READ THIS","Within about +/-10 of the truth you make $500-$1,250. Off by 20+ you lose. Semi-auto moves the burden onto YOUR read (your edge), and the machine handles sizing + discipline."],
[""],
["WHY ONLY 13 TRADES on the 75 run","With a good read the right bracket is underpriced the whole way, so the bot correctly ACCUMULATES it and holds - it doesn't churn. Back-and-forth only appears when the two brackets are genuinely balanced (read 70 = 45 trades, read 85 = 71). Hundreds of trades is not the goal; being right and sized correctly is. If you want a take-profit scalp overlay for more round-trips, vAI can add it (it usually LOWERS profit by selling winners early)."],
[""],
["TABS","'Config' = bankroll / Kelly fraction / clip cap (change these and the trade math recomputes). 'Per-Post Pace' = your read vs the count, per tweet, with the fair prices. 'Every Trade' = each trade with our pace, the PM odds, our fair, the edge, Kelly, EV, and shares+value as live formulas."],
]
config=[["SEMI-AUTO CONFIG (edit B1:B3, the Every Trade formulas recompute)"],
        ["Bankroll ($)",5000],["Kelly fraction",0.25],["Clip cap ($ per buy)",40]]

# ---- Per-Post Pace with descriptions ----
fair_cols=[c for c in tw.columns if c.startswith('fair_')]
tw_hdr=['tweet_no','et','hrs_to_close','count_so_far','human_center','eff_center','sigma']+fair_cols
desc_tw={'tweet_no':'Nth counted tweet in the auction','et':'When the tweet posted (Eastern)','hrs_to_close':'Hours left until resolution',
 'count_so_far':'Tweets counted so far this auction','human_center':'YOUR count read for the final total (the input the 61% model cannot beat)',
 'eff_center':'Effective center used = your read, never below count-so-far','sigma':'Our uncertainty band in tweets; shrinks as time runs out so fair prices sharpen'}
for c in fair_cols: desc_tw[c]=f'Our fair probability for bracket {c[5:]} given the pace + sigma'
tw_rows=[tw_hdr,[desc_tw[c] for c in tw_hdr]]
for _,r in tw.iterrows(): tw_rows.append([('' if pd.isna(r[c]) else r[c]) for c in tw_hdr])

# ---- Every Trade with descriptions + formulas ----
tcols=['et','hrs_to_close','action','bracket','our_pace','pm_odds','our_fair']  # A..G
hdr=['Time (ET)','Hrs to close','Action','Bracket','Our pace (count)','PM odds','Our fair','Edge','Kelly fraction','Expected value ($)','Shares','Total value ($)']
desc=['When the trade fired (Eastern)','Hours left until the auction resolves','BUY = market below our fair; SELL = market above our fair',
 'The tweet-count bracket traded','Our effective projected final count (your read, floored at count-so-far)',
 "Polymarket's price for this bracket = the market's implied probability",'Our fair probability this bracket wins (pace + shrinking uncertainty)',
 'Our fair minus the market price. + = underpriced (buy), - = overpriced (sell)','Kelly bet fraction = edge / (1 - price)',
 'Shares x edge = expected profit of this clip [formula]','Kelly-sized: min(bankroll x fraction x Kelly, clip cap) / price [formula]','Shares x price = dollars deployed [formula]']
tr_rows=[hdr,desc]
for i in range(len(tr)):
    r=tr.iloc[i]; R=i+3  # data starts at sheet row 3
    tr_rows.append([r['et'],r['hrs_to_close'],r['action'],r['bracket'],r['our_pace'],r['pm_odds'],r['our_fair'],
        f"=G{R}-F{R}", f"=(G{R}-F{R})/(1-F{R})", f"=K{R}*(G{R}-F{R})",
        f"=MIN(Config!$B$2*Config!$B$3*I{R},Config!$B$4)/F{R}", f"=K{R}*F{R}"])

TABS=[("Read me",readme,0),("Config",config,0),("Per-Post Pace",tw_rows,2),("Every Trade",tr_rows,2)]
ss=sh.spreadsheets().create(body={'properties':{'title':'SEMI-AUTO Seesaw - trade-by-trade + Kelly sizing (formulas)'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':t[2]}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'USER_ENTERED','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; GRAY={'red':0.92,'green':0.92,'blue':0.92}; reqs=[]
# Read me formatting
sid=idm['Read me']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':230},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':820},'fields':'pixelSize'}})
sid=idm['Config']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':170},'fields':'pixelSize'}})
# header + description rows for data tabs
for nm,nc in [('Per-Post Pace',len(tw_hdr)),('Every Trade',12)]:
    sid=idm[nm]
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':GRAY,'textFormat':{'italic':True,'fontSize':9},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
# Every Trade: buy/sell color on col C, green/red on Edge col H
sid=idm['Every Trade']
for val,color in [("BUY",{'red':0.83,'green':0.94,'blue':0.83}),("SELL",{'red':0.99,'green':0.90,'blue':0.80})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':2,'endRowIndex':len(tr_rows),'startColumnIndex':2,'endColumnIndex':3}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':12},'properties':{'pixelSize':105},'fields':'pixelSize'}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
