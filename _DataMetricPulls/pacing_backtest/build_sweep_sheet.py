# -*- coding: utf-8 -*-
"""Sheet: the seesaw dip-buy verdict. Grid (16 configs all losing), per-auction, every dip-buy, audit."""
import os
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
grid=pd.read_csv(f"{D}/grid_matrix.csv"); auc=pd.read_csv(f"{D}/sweep_seesaw_auctions.csv"); buys=pd.read_csv(f"{D}/sweep_seesaw_buys.csv")
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)

verdict=[
["SEESAW DIP-BUY on 2 pace-model-picked brackets - THE VERDICT"],
[""],
["HEADLINE","It loses. Every single one of 16 configurations is negative. Best -9.8%, worst -45.5%. 18 two-day Apr-Jun auctions, event-driven (every tweet + every price tick, millisecond merge), NO look-ahead, walk-forward locked Ens+CAP1.5 pace model picking the 2 brackets live."],
[""],
["WHY IT LOSES (one number)","The winner lands inside our 2 picked brackets only 61% of the time. Break-even needs ~79%. Every miss is a near -100% auction. 61% x (+27% when right) + 39% x (-100% when wrong) = net negative. No exit rule fixes a wrong bracket pick."],
["THE EFFICIENCY WALL","Picking the 2 brackets from the MARKET's own implied center scores the EXACT same 61% hit-rate as our pace model. Neither out-selects the other. The market knows what we know. The dip-buy adds no alpha on top - buying the fade just changes entry price on a coin-flip bracket bet."],
["THE TAIL IS THE KILLER","6 of 7 total wipeouts are UNDER-projection: Elon out-tweeted our model and the winner was a HIGHER bracket than we bought (april-23 act79 we bought <40-64; may-16 act86 we bought 40-64; june-1 act69 we bought 40-64). The 1.5x rate CAP we locked for stability is exactly what parks us in too-low brackets on his active auctions."],
[""],
["ADVERSARIAL AUDIT","5 independent auditors tried to break this backtest. Verdict: the -9.8% is HONEST and if anything FLATTERING."],
["  - no fabricated edge","No look-ahead leak that invents profit. Winners are correct (settled YES, actual count inside the bucket)."],
["  - the -9.8% is optimistic","The one HIGH-severity bug (fills book the full tranche at top-of-book with zero depth) INFLATES the winning brackets. Real fills get fewer shares on deep dips, so the true result is WORSE than -9.8%, not better."],
["  - fixed","Event ordering (ms-native merge, tweet-before-price) applied; base moved -10.8% -> -9.8% (immaterial, confirms robustness)."],
[""],
["STRATEGIST READ","Automated bracket-selection on Elon is efficient = dead. This is the THIRD confirmation (divergence scalp, complement-pair arb, now the seesaw). We can MATCH the market's fair value (61% = same as them) but not BEAT it. The dip-buy is not the problem; SELECTION is, and selection is efficient."],
[""],
["THE WINNING MOVE (2 paths)"],
["1. Test an uncapped burst-aware SELECTOR","6/7 wipeouts are under-projection. An uncapped / burst-aware model used ONLY to pick the 2 brackets (not to replace the locked projection) directly targets the failure. NOTE: you locked the pace model and told vAI never to substitute it without asking - so vAI will NOT touch it without your explicit yes. This is the single highest-EV next test."],
["2. Semi-automate","Your manual edge (if real) lives in discretionary bracket selection the 61% model cannot reach. Let YOU call the 2 brackets; the bot runs the disciplined dip-buy + scalp execution around your call. Marries your edge to the bot's discipline/speed."],
[""],
["TABS","'Config Grid' = all 16 variants ranked. 'Per Auction' = the 18 auctions, which brackets we picked, did the winner land there, P&L. 'Every Dip-Buy' = trade by trade. 'Audit' = the 5-lens findings."],
]

AUD=[
["lens","verdict","severity","makes result look","finding","fix"],
["Look-ahead / the wall","CONCERN","low","either","Universe is selected on outcome (resolved) + full-window liquidity (>=500 ticks) - survivorship at the universe stage, not a per-trade leak.","Report drops; use a causal first-N-hours liquidity gate."],
["Scoring & winner","CONCERN","low","none","Winners correct, but only 5/18 are direct Gamma; 13 inferred from close=0.999. Label was 'Gamma-confirmed' - reword.","Say 'resolved_yes OR resolved_yes_gamma'. No numeric impact."],
["Scoring & winner","CONCERN","med","none","'61% hit' measures winner-in-BOUGHT not winner-in-PICKED; some picked-but-not-bought misses. True pick-coverage is >61% (conservative).","Add a separate winner-in-picked stat. Doesn't change ROI."],
["Fill realism","BUG","HIGH","INFLATES","Zero-depth fill: full $50 tranche books at top-of-book ask (a 0.2c dip => 25,000 phantom shares). Overstates winning-bracket payoff.","Cap fills to real resting size (pmxt has it). Re-run: ROI goes BELOW -9.8%."],
["Fill realism","BUG","med","either","Buys cross to the ask (taker) though bot is maker-only; no fees, no latency, guaranteed instant fill.","Decide maker (rest post-only bid) vs taker (add fees+latency)."],
["Model fidelity","CONCERN","low","either","rmean/Kk priors drawn from the token-filtered set, not the full count-history the locked leaderboard uses - shifts projections slightly.","Build priors from full count-history; keep token filter only for tradeability."],
["Event-driven","CONCERN","med","either","(FIXED) ts truncated to seconds put all ticks before tweets in the same second, inverting tweet->price order.","Merge on native ms, tweet-before-price tie-break. Applied; -10.8%->-9.8%."],
]

def df_rows(df,cols=None):
    cols=cols or list(df.columns); out=[cols]
    for _,r in df.iterrows(): out.append([('' if pd.isna(r[c]) else r[c]) for c in cols])
    return out
grid_t=df_rows(grid[['label','select','nbrk','mode','conv','n_traded','pooled_roi_pct','win_rate_pct','median_roi_pct','bracket_hit_pct']])
auc_t=df_rows(auc[['slug','winner','actual','brackets_bought','winner_bought','deployed','payoff','pnl','roi%','nbuys']])
buys_t=df_rows(buys[['slug','et','hrs_to_close','proj','bracket','buy_price','won']])

TABS=[("Verdict",verdict,0),("Config Grid",grid_t,1),("Per Auction",auc_t,1),("Every Dip-Buy",buys_t,1),("Audit",AUD,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'Seesaw Dip-Buy - Verdict + Grid + Trade-by-Trade + Audit'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
sid=idm['Verdict']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':230},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':860},'fields':'pixelSize'}})
for nm,nc in [('Config Grid',10),('Per Auction',10),('Every Dip-Buy',7),('Audit',6)]:
    reqs.append({'repeatCell':{'range':{'sheetId':idm[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
# color ROI red/green in grid (col 6) and per-auction (col 8 pnl)
for sidn,ci,ln in [('Config Grid',6,len(grid_t)),('Per Auction',7,len(auc_t))]:
    sid=idm[sidn]
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':ln,'startColumnIndex':ci,'endColumnIndex':ci+1}],'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':{'red':0.98,'green':0.85,'blue':0.83}}}},'index':0}})
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':ln,'startColumnIndex':ci,'endColumnIndex':ci+1}],'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':{'red':0.83,'green':0.94,'blue':0.83}}}},'index':0}})
# winner_bought YES/no in per-auction (col 4)
sid=idm['Per Auction']
for val,color in [("YES",{'red':0.83,'green':0.94,'blue':0.83}),("no",{'red':0.98,'green':0.88,'blue':0.86})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(auc_t),'startColumnIndex':4,'endColumnIndex':5}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
# won WIN/lose in dip-buy (col 6)
sid=idm['Every Dip-Buy']
for val,color in [("WIN",{'red':0.83,'green':0.94,'blue':0.83}),("lose",{'red':0.98,'green':0.88,'blue':0.86})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(buys_t),'startColumnIndex':6,'endColumnIndex':7}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
# Audit tab widths + wrap
sid=idm['Audit']
for ci,w in [(0,140),(1,90),(2,80),(3,110),(4,430),(5,360)]:
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':w},'fields':'pixelSize'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(AUD),'startColumnIndex':4,'endColumnIndex':6},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
