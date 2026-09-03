# -*- coding: utf-8 -*-
"""Sheet: the tweet-reaction SPEED test - physics + latency-swept P&L for Test B (grab the jump) and
Test A (dodge the drop). Numbers from measure_tweet_reaction.py + speed_sim.py (verified runs)."""
import os
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
D="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot/_DataMetricPulls/pacing_backtest/audit_out3"
R=pd.read_csv(f"{D}/tweet_reaction.csv"); ev=R[R.eventful]
WINS=[500,1000,2000,5000,15000,60000,300000]; lab={500:'0.5s',1000:'1s',2000:'2s',5000:'5s',15000:'15s',60000:'60s',300000:'5min'}
def offrow(off,name):
    sub=ev[ev.offset==off]; row=[name,len(sub)]+[round(100*sub[f'd{W}'].mean(),2) if len(sub) else '' for W in WINS]; return row
phys=[["bracket vs current","n"]+[lab[W] for W in WINS]]
for off,name in [(-2,"-2"),(-1,"-1 (early)"),(0,"0 (current)"),(1,"+1 (long)"),(2,"+2"),(3,">= +3 (far)")]:
    phys.append(offrow(off,name))

creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)

verdict=[
["TWEET-REACTION SPEED TEST - can we trade the move Elon's tweets make?"],
[""],
["THE PHYSICS (confirmed your read)","Across 22 Apr-Jun auctions, last 24h, 533 tweets: 67% are EVENTFUL (move the book >= 2c). When one hits, the NEXT-HIGHER bracket (+1) JUMPS about +2.9c over 60s, the EARLY (-1) and CURRENT brackets DROP about -2.6c / -2.0c, and +2 / far brackets barely move. The action is entirely in the two ADJACENT brackets. Exactly what you described."],
["THE SPEED","Market reaction ONSET = median 422ms (p25 260ms) after the tweet. The jump is fast but not instant: ~40% of the 60s move is done by 500ms, 76% by 15s, 100% by 60s. So a sub-400ms bot has a real - but tiny - head start."],
[""],
["TEST B - GRAB THE JUMP (buy +1 on the tweet, sell 60s later)","VIABLE, but only on a knife-edge. Per $50 taker clip, holding 60s: +$3.47 at 0ms (impossible), +$2.02 at 250ms, about ZERO at 500ms, negative beyond. The entire edge lives in the first ~400ms. Miss that window and the spread eats you."],
["TEST A - DODGE THE DROP (sell early+current on the tweet, rebuy later)","DEAD. Best case +$0.34 per clip at 0ms / 60s; negative at ANY real latency. Selling at the bid and rebuying at the ask pays two spreads, which costs more than the ~2.6c drop you dodge."],
[""],
["THE BLOCKER YOU NEED TO DECIDE","BOTH plays are TAKER by nature - you must CROSS THE SPREAD to react in time. The bot is LOCKED maker-only (post-only, never takes). So this speed play needs a carve-out: a TAKER 'hot lane' just for the tweet-reaction arb. Without it, the play is off the table. With it, you are betting the bot can hit sub-400ms tweet-to-fill consistently (Dublin VPS + TwitterAPI.io + warm pool). That is elite and fragile: 250ms = +$2/clip, 500ms = $0."],
[""],
["HONEST CAVEATS","(1) Fills assume a $50 clip fits at top-of-book; grabbing real SIZE walks up the ask ladder and degrades every number - depth-capped validation on our full-L2 recorder is the next step. (2) Tweets end Jun 29, so this is 22 auctions Apr-Jun. (3) FEE modeled at 0 (Polymarket); the SPREAD is the real cost and it is already in the fills. (4) No look-ahead: the +1 bracket is chosen from the PRE-tweet center; every fill price is read at our own action time T+latency."],
[""],
["SO WHAT / RECOMMENDATION","The move is real and it is your instinct, but only 'buy the +1 jump' survives, only sub-400ms, only as a taker. Next step if you want it: (a) decide on the taker hot-lane carve-out, (b) vAI runs the DEPTH-CAPPED version on the recorder's full L2 to see if it holds at tradeable size and to pin the real latency budget. That is the make-or-break test before any build."],
[""],
["TABS","'Tweet Physics' = the move by bracket-offset x time window. 'Speed Sim B' = grab-the-jump P&L by latency x hold. 'Speed Sim A' = dodge-the-drop P&L by latency x hold."],
]

# sim grids (verified runs), cents of P&L per $50 clip
simB=[["latency \\ hold","5s","15s","60s"],
["0ms (ideal)","-12.09","+97.20","+347.44"],
["250ms","-147.59","-40.26","+201.83"],
["500ms","-341.42","-240.25","-4.83"],
["1000ms","-354.56","-272.84","-37.08"],
["2000ms","-377.69","-303.15","-83.23"]]
simA=[["latency \\ hold","5s","15s","60s"],
["0ms (ideal)","-182.47","-94.36","+34.07"],
["250ms","-398.15","-306.14","-155.13"],
["500ms","-601.96","-504.02","-328.25"],
["1000ms","-601.13","-506.22","-337.74"],
["2000ms","-600.80","-534.97","-354.58"]]

TABS=[("Verdict",verdict,0),("Tweet Physics",phys,1),("Speed Sim B",simB,1),("Speed Sim A",simA,1)]
ss=sh.spreadsheets().create(body={'properties':{'title':'Tweet-Reaction SPEED Test - Physics + Latency-Swept P&L'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']; idm={x['properties']['title']:x['properties']['sheetId'] for x in ss['sheets']}
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]}).execute()
DARK={'red':0.13,'green':0.18,'blue':0.22}; reqs=[]
sid=idm['Verdict']
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13}}},'fields':'userEnteredFormat(textFormat)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':1,'endColumnIndex':2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1},'properties':{'pixelSize':230},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':1,'endIndex':2},'properties':{'pixelSize':880},'fields':'pixelSize'}})
for nm,nc in [('Tweet Physics',9),('Speed Sim B',4),('Speed Sim A',4)]:
    reqs.append({'repeatCell':{'range':{'sheetId':idm[nm],'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':nc},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
# green/red for the sim grids (cols 1..3) via number formatting won't apply to strings; color by conditional on text starting with +/-
for nm,nr in [('Speed Sim B',6),('Speed Sim A',6)]:
    sid=idm[nm]
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':nr,'startColumnIndex':1,'endColumnIndex':4}],'booleanRule':{'condition':{'type':'TEXT_STARTS_WITH','values':[{'userEnteredValue':'+'}]},'format':{'backgroundColor':{'red':0.80,'green':0.94,'blue':0.80}}}},'index':0}})
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':nr,'startColumnIndex':1,'endColumnIndex':4}],'booleanRule':{'condition':{'type':'TEXT_STARTS_WITH','values':[{'userEnteredValue':'-'}]},'format':{'backgroundColor':{'red':0.98,'green':0.85,'blue':0.83}}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
try: dr.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as ex: print('share warn',ex)
print("SHEET_URL:",dr.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink'])
