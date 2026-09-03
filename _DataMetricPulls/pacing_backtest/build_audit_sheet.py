"""Build a fully-transparent Google Sheet from the REAL audit CSVs (audit_out/).
Every number traces to a per-trade fill. Uses DWD service account (subject=darwin@xagency.com)."""
import os, json
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out"
ad=pd.read_csv(f"{OUT}/auctions_detail.csv"); tr=pd.read_csv(f"{OUT}/trades_detail.csv"); sm=pd.read_csv(f"{OUT}/summary.csv")
G=ad[ad.run=='gated'].copy().sort_values('win_start_ET'); GT=tr[tr.run=='gated'].copy()

creds=service_account.Credentials.from_service_account_file(
    os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],
    subject='darwin@xagency.com')
sheets=build('sheets','v4',credentials=creds); drive=build('drive','v3',credentials=creds)

# ---------- derived facts (all from real data) ----------
n2=(G.dur=='2-day').sum(); n7=(G.dur=='7-day').sum()
klong=GT[GT.strategy=='kalman_edge']
kbest=klong.loc[klong['pnl_$'].idxmax()]
k_total=klong['pnl_$'].sum(); k_best_share=100*kbest['pnl_$']/k_total
k7_share=100*klong[klong.dur=='7-day']['pnl_$'].sum()/k_total
dmin=G['win_start_ET'].min()[:10]; dmax=G['win_end_ET'].max()[:10]

def seg(lbl,st):
    r=sm[(sm.segment==lbl)&(sm.strategy==st)]
    return (float(r['roi_pct'].iloc[0]),float(r['pnl_$'].iloc[0]),float(r['capital_deployed_$'].iloc[0])) if len(r) else (0,0,0)
GATE="WITH 2-days-left gate (Sir's rule) | 2-day only"
hf=seg(GATE,'hold_fav'); ke=seg(GATE,'kalman_edge'); sh=seg(GATE,'scrape_hold'); ss=seg(GATE,'scrape_sell')

# ---------- TAB 1: READ ME FIRST ----------
readme=[
["READ ME FIRST  —  What this backtest actually is, in plain English"],
[""],
["In one sentence","The fancy strategy's headline win is a mirage from ONE lucky trade; on the honest sample the SIMPLEST strategy (buy the favorite, hold) wins, and there is no proven edge."],
[""],
["What we did","Simulated 4 trading strategies on REAL Polymarket order-book history (best bid/ask, tick by tick) for Elon Musk tweet-count bracket markets. Every 'buy' fills at the real best-ASK price that existed at that moment; every position resolves by the ACTUAL number of tweets Elon posted in the noon-to-noon window."],
["Markets tested",f"{len(G)} auctions total: {n2} two-day markets + {n7} seven-day market. All resolved between {dmin} and {dmax} 2026 (that is the window where we have order-book history)."],
["Bankroll assumed",f"${5394:,.0f}. Bet sizing = fractional Kelly (0.25x) off expected value, capped at 10% of bankroll, further capped by the real order-book depth available."],
[""],
["THE HEADLINE THAT LOOKS GREAT (and why you should not trust it)"],
["'kalman_edge' shows +90.8% ROI overall",f"But 90% of its ENTIRE profit (${k_total:,.0f}) came from a SINGLE trade: it bought the '{kbest['bracket']}' bracket at {kbest['entry_ask']*100:.1f} cents on the June 19-26 week, that bracket won, and it paid off +${kbest['pnl_$']:,.0f}."],
["Concentration",f"That one trade = {k_best_share:.0f}% of all kalman profit. The whole 7-day market = {k7_share:.0f}%. Take that one week out and the 'edge' collapses to middling."],
[""],
["THE HONEST RESULT (the sample big enough to mean anything = 18 two-day markets)"],
["hold_fav  (buy the favorite bracket, hold to end)",f"{hf[0]:+.1f}% ROI   <-- WINNER, and it is the dumbest strategy"],
["scrape_hold  (blind dip-buy, hold to end)",f"{sh[0]:+.1f}% ROI"],
["kalman_edge  (the fancy model)",f"{ke[0]:+.1f}% ROI   <-- ties the blind strategies once the lucky week is gone"],
["scrape_sell  (buy dip, sell the pop)",f"{ss[0]:+.1f}% ROI   <-- the scalp is the weakest"],
[""],
["CONCLUSION","No proven edge on this market. The fancy model does not beat buy-and-hold once you remove one lucky week. Consistent with every other test: this market is efficient. Trust hold-based logic, drop the scalp, and do NOT size real money off the +90% headline."],
[""],
["HOW TO CHECK ME (this is the point of this sheet)"],
["Tab 'Universe'","Every market we tested: which one, its window, how many tweets actually happened, which bracket won, where the order-book data came from."],
["Tab 'Per-Auction P&L'","For each market, what each strategy made or lost. You will SEE the June 19-26 row is the whole story for kalman."],
["Tab 'Every Trade'","Every single simulated fill: the bracket, the real ask price paid, the size, win/lose, the P&L. Add up this tab's P&L and you get the summary exactly."],
["Tab 'Results Summary'","The roll-ups, with and without Sir's 2-days-left gate, split by 2-day vs 7-day."],
["Tab 'Limitations'","Everything this does NOT prove, stated bluntly."],
["Tab 'Methodology & Data'","Exactly how a fill is computed, the Kelly formula, the data sources and their coverage."],
[""],
["Built from","real_fill_v5_audit.py  ->  audit_out/{auctions_detail,trades_detail,summary}.csv. Re-runnable any time; same code, same numbers."],
]

# ---------- TAB 2: UNIVERSE ----------
uni_hdr=["#","Market (slug)","Type","Window start (ET)","Window end (ET)","Enter from (ET, Sir's gate)","Hours","Actual tweets","Winning bracket","# brackets","L2 source","# order-book rows","# hourly snapshots"]
uni=[uni_hdr]
for i,(_,r) in enumerate(G.iterrows(),1):
    uni.append([i,r['slug'],r['dur'],r['win_start_ET'],r['win_end_ET'],r['entry_from_ET'],r['window_hours'],
                int(r['actual_tweet_count']),r['winner_bracket'],int(r['n_brackets']),
                'pmxt archive' if r['src']=='pmxt' else 'our recorder',int(r['n_l2_price_rows']),int(r['n_grid_hours'])])
uni.append([])
uni.append(["Funnel","56 auctions were collected (54 two-day + 2 seven-day). 19 survived to the test. The other 37 were dropped because there was NO order-book history in their trading window (pmxt L2 starts 2026-04-13; our recorder starts 2026-06-23), or they had fewer than 3 hourly snapshots, or the winner could not be resolved."])

# ---------- TAB 3: STRATEGY DEFINITIONS ----------
strat=[
["Strategy","Plain English","Entry trigger (exact)","Sizing","Exit","In the bot today?"],
["hold_fav","Buy the bracket the market thinks is most likely (the favorite), at the middle of the window, and hold to resolution.","At the mid-window hour, pick the bracket with the highest YES ask; buy if model-prob > ask (positive EV).","Fractional Kelly (0.25x) off EV, capped 10% of bank, capped by depth.","Hold to resolution (win = $1, lose = $0).","Closest to 'hold till the end'."],
["scrape_sell","Buy a dip in the most 'in-play' bracket (price near 50c) and sell into the next pop. A scalp.","Track the ~50/50 bracket; buy when mid-price drops >4c below its EMA(6); sell when it pops >4c above EMA or falls 6c below entry (stop).","Fixed 2% of bank per trade, capped by depth.","Sell at the bid on the pop/stop (round-trip, does not hold).","'scrape and sell'."],
["scrape_hold","Blindly buy any bracket that dips to a new local low, then hold to resolution. No model.","For each bracket, buy the first time its ask breaks below the trailing 4-hour min (by >0.5c), price between 2c and 90c.","Fixed 2% of bank per trade, capped by depth.","Hold to resolution.","'scrape and hold'."],
["kalman_edge","The fancy one. Use a Kalman pace model to project the final tweet count, turn that into a fair probability per bracket, and buy any bracket trading >3c below fair.","For each bracket with model-prob >= 8%, buy the first hour its ask < (model fair - 3c) and fair > 5c.","Fractional Kelly (0.25x, x Brier throttle) off (fair - ask), capped 10%, capped by depth.","Hold to resolution.","NEW — this is the one being tested for the rebuild."],
]

# ---------- TAB 4: PER-AUCTION P&L (gated) ----------
pa_hdr=["Market (slug)","Type","Actual tweets","Winner","Model prob (winner)","Market price (winner)","hold_fav P&L $","scrape_sell P&L $","scrape_hold P&L $","kalman_edge P&L $","Note"]
pa=[pa_hdr]
for _,r in G.iterrows():
    note=""
    if r['dur']=='7-day': note="<-- THE ONE LUCKY WEEK. This single 7-day market is 87% of all kalman profit."
    pa.append([r['slug'],r['dur'],int(r['actual_tweet_count']),r['winner_bracket'],
               r['model_implied_prob_winner'],r['market_price_prob_winner'],
               r['hold_fav_pnl'],r['scrape_sell_pnl'],r['scrape_hold_pnl'],r['kalman_edge_pnl'],note])
tot=["TOTAL (all 19, gated)","","","","","",round(G['hold_fav_pnl'].sum(),2),round(G['scrape_sell_pnl'].sum(),2),round(G['scrape_hold_pnl'].sum(),2),round(G['kalman_edge_pnl'].sum(),2),""]
tot2=["TOTAL (18 two-day only)","","","","","",
      round(G[G.dur=='2-day']['hold_fav_pnl'].sum(),2),round(G[G.dur=='2-day']['scrape_sell_pnl'].sum(),2),
      round(G[G.dur=='2-day']['scrape_hold_pnl'].sum(),2),round(G[G.dur=='2-day']['kalman_edge_pnl'].sum(),2),"remove the lucky 7-day and kalman is just average"]
pa.append([]); pa.append(tot); pa.append(tot2)

# ---------- TAB 5: EVERY TRADE (gated) ----------
et_hdr=["Market (slug)","Type","Strategy","Bracket","Entry ask (¢)","Stake $","Filled $","Shares","Won?","P&L $","What happened"]
et=[et_hdr]
for _,r in GT.sort_values(['slug','strategy']).iterrows():
    et.append([r['slug'],r['dur'],r['strategy'],r['bracket'],round(r['entry_ask']*100,2),r['stake_$'],r['fill_$'],
               r['shares'],'YES' if r['won'] else 'no',r['pnl_$'],r['note']])

# ---------- TAB 6: RESULTS SUMMARY ----------
rs=[["Segment","# markets","Strategy","Capital deployed $","P&L $","ROI %"]]
order=["WITH 2-days-left gate (Sir's rule) | ALL","WITH 2-days-left gate (Sir's rule) | 2-day only","WITH 2-days-left gate (Sir's rule) | 7-day only",
       "WITHOUT gate | ALL","WITHOUT gate | 2-day only","WITHOUT gate | 7-day only"]
for lbl in order:
    sub=sm[sm.segment==lbl]
    for st in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']:
        r=sub[sub.strategy==st]
        if len(r): rs.append([lbl,int(r['n_auctions'].iloc[0]),st,float(r['capital_deployed_$'].iloc[0]),float(r['pnl_$'].iloc[0]),float(r['roi_pct'].iloc[0])])
    rs.append([])
rs.append(["READ THIS","","","","",""])
rs.append(["The 2-day-only rows are the only ones with enough markets (18) to trust. 7-day is a single market (noise). The 'gate' (only trade in the last 48h) changes nothing for 2-day markets because a 2-day market IS the last 48h.","","","","",""])

# ---------- TAB 7: LIMITATIONS ----------
lim=[
["Limitations — what this backtest does NOT prove"],
[""],
["Sample size","18 two-day markets and 1 seven-day market. That is small. A strategy can look good or bad on 18 markets by luck alone. Treat every ROI here as a hint, not a fact."],
["The 7-day is a single data point","+1067% on one market is noise, full stop. We have exactly one resolved 7-day market inside the order-book window. It proves nothing about 7-day markets."],
["Self-resolved winners","The winning bracket is computed from our own tweet-count backfill (Sept 2025+, validates 82-86% vs the market's official count), NOT from Polymarket's official resolution for these specific markets. A miscount near a bracket edge could flip a win/loss."],
["Fill model is optimistic","Each hourly ask is the LAST best-ask in that hour. We assume we could buy at that price for up to the top-2-levels of depth, with no slippage, no queue position, no partial fills, and instant execution. Real fills are worse."],
["No fees / no maker rebate","These sims take liquidity at the ask (taker). The real bot is maker-only. So both the costs and the rebates are missing — the real economics differ."],
["No transaction costs beyond the ask","Gas, spread on exit, and adverse selection are not modeled."],
["Kelly assumes the model is right","kalman_edge sizes bets as if its fair-value estimate is correct. If the model is biased, Kelly over-bets. The Brier throttle dampens this but does not remove it."],
["Look-ahead controls","The pace model only uses data up to each decision hour (walk-forward), and priors only from EARLIER auctions. But the bracket set, the noon window, and the resolution are known up front by construction — standard for this kind of test."],
["Survivorship","37 of 56 collected markets were dropped for lack of order-book data. The 19 that remain are the most recent ones; they are not a random sample of all history."],
["Bottom line","This is enough to RANK strategies directionally (hold beats scalp; fancy does not beat simple) and to KILL the +90% headline. It is NOT enough to justify deploying real money at any of these ROI numbers."],
]

# ---------- TAB 8: METHODOLOGY & DATA ----------
meth=[
["Methodology & Data"],
[""],
["HOW A FILL IS COMPUTED"],
["Price data","For each market we pull every order-book event (best_bid, best_ask) and bucket it by hour, taking the LAST ask/bid in each hour (arg_max by timestamp)."],
["A 'buy'","shares = dollars_filled / ask.  dollars_filled = min(stake, depth).  P&L = shares x (payout - ask), where payout = $1 if that bracket won, else $0."],
["Depth cap","depth = median dollar value of the top-2 ask levels seen in that market's order book. You cannot fill more than the book holds."],
["SIZING (fractional Kelly off EV)"],
["Formula","stake = clip( EV/(1-ask) x 0.25 , 0, 0.10 ) x bankroll.  EV = model_prob - ask (or fair - ask).  0.25 = quarter-Kelly. 0.10 = 10% max bet."],
["Brier throttle (kalman only)","multiplies the Kelly fraction by clip(market_Brier / model_Brier, 0.5, 1.3) using the last 8 auctions — bets less when the model has been worse-calibrated than the market."],
["SIR'S 2-DAYS-LEFT GATE"],
["Rule","Only trade inside the final 48 hours of a market. For a 2-day market that is the whole window (so the gate changes nothing). For a 7-day/monthly market it means we ignore the first 5 days."],
["DATA SOURCES + COVERAGE"],
["Tweet counts","elon_backfill_2025-09_to_now.parquet (X-API, Sept 2025+, counts main-feed originals+quotes+reposts+self-replies). Used to resolve winners and drive the pace model."],
["Order book — pmxt","Free archive.pmxt.dev, complete tick L2 for every market from 2026-04-13. Covers the historical 2-day markets."],
["Order book — our recorder","Railway tweet-recorder, from 2026-06-23. Covers the recent 2-day + 7-day markets. No overlap with pmxt (deduped: pmxt owns up to Jun 22 23:00, recorder owns Jun 23 18:00+)."],
["Window definition","Every market runs noon ET to noon ET, parsed from the market's own dates (e.g. 'june-19-june-26' = Jun 19 12:00 ET to Jun 26 12:00 ET)."],
["Code","real_fill_v5_audit.py — identical logic to real_fill_v5.py, plus per-trade logging. Deterministic; re-run gives identical CSVs."],
]

TABS=[("READ ME FIRST",readme,0),("1. Universe",uni,1),("2. Strategy Definitions",strat,1),
      ("3. Per-Auction P&L",pa,1),("4. Every Trade",et,1),("5. Results Summary",rs,1),
      ("6. Limitations",lim,0),("7. Methodology & Data",meth,0)]

# ---------- create spreadsheet ----------
ss=sheets.spreadsheets().create(body={'properties':{'title':'Elon Backtest — What We ACTUALLY Tested (Audit)'},
    'sheets':[{'properties':{'title':t[0],'gridProperties':{'frozenRowCount':1 if t[2] else 0}}} for t in TABS]}).execute()
SID=ss['spreadsheetId']
idmap={s['properties']['title']:s['properties']['sheetId'] for s in ss['sheets']}
# write values
data=[{'range':f"'{t[0]}'!A1",'values':t[1]} for t in TABS]
sheets.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'RAW','data':data}).execute()

# ---------- formatting ----------
DARK={'red':0.26,'green':0.26,'blue':0.26}; GOLD={'red':0.83,'green':0.667,'blue':0.36}
reqs=[]
def fmt_header(sid,ncol):
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':ncol},
        'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},
        'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
def title_row(sid):
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':1},
        'cell':{'userEnteredFormat':{'textFormat':{'bold':True,'fontSize':13,'foregroundColor':DARK}}},'fields':'userEnteredFormat(textFormat)'}})
def wrap(sid,ncol):
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startColumnIndex':0,'endColumnIndex':ncol},
        'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
def colw(sid,idx,px):
    reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':idx,'endIndex':idx+1},'properties':{'pixelSize':px},'fields':'pixelSize'}})
def boldcol0(sid,rows):
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':rows,'startColumnIndex':0,'endColumnIndex':1},
        'cell':{'userEnteredFormat':{'textFormat':{'bold':True}}},'fields':'userEnteredFormat(textFormat)'}})

# text tabs
for name,rows in [("READ ME FIRST",readme),("6. Limitations",lim),("7. Methodology & Data",meth)]:
    sid=idmap[name]; title_row(sid); wrap(sid,2); colw(sid,0,300); colw(sid,1,760); boldcol0(sid,len(rows))
# universe
sid=idmap["1. Universe"]; fmt_header(sid,len(uni_hdr)); wrap(sid,len(uni_hdr)); colw(sid,1,300); colw(sid,3,150); colw(sid,4,150); colw(sid,5,170)
# strategy
sid=idmap["2. Strategy Definitions"]; fmt_header(sid,6); wrap(sid,6)
for i,w in enumerate([110,300,340,220,220,150]): colw(sid,i,w)
# per-auction
sid=idmap["3. Per-Auction P&L"]; fmt_header(sid,len(pa_hdr)); wrap(sid,len(pa_hdr)); colw(sid,0,270); colw(sid,10,360)
# highlight 7-day rows red-ish
for ri,(_,r) in enumerate(G.iterrows(),1):
    if r['dur']=='7-day':
        reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':ri,'endRowIndex':ri+1,'startColumnIndex':0,'endColumnIndex':len(pa_hdr)},
            'cell':{'userEnteredFormat':{'backgroundColor':{'red':1,'green':0.9,'blue':0.9}}},'fields':'userEnteredFormat(backgroundColor)'}})
# color P&L columns green/red via conditional format (cols 6-9)
for c in range(6,10):
    for cond,color in [("NUMBER_GREATER",{'red':0.85,'green':0.94,'blue':0.85}),("NUMBER_LESS",{'red':0.98,'green':0.85,'blue':0.85})]:
        reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(G)+1,'startColumnIndex':c,'endColumnIndex':c+1}],
            'booleanRule':{'condition':{'type':cond,'values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':color}}},'index':0}})
# every trade
sid=idmap["4. Every Trade"]; fmt_header(sid,len(et_hdr)); wrap(sid,len(et_hdr)); colw(sid,0,270); colw(sid,10,320)
for cond,color in [("NUMBER_GREATER",{'red':0.85,'green':0.94,'blue':0.85}),("NUMBER_LESS",{'red':0.98,'green':0.85,'blue':0.85})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':1,'endRowIndex':len(GT)+1,'startColumnIndex':9,'endColumnIndex':10}],
        'booleanRule':{'condition':{'type':cond,'values':[{'userEnteredValue':'0'}]},'format':{'backgroundColor':color}}},'index':0}})
# summary
sid=idmap["5. Results Summary"]; fmt_header(sid,6); wrap(sid,6); colw(sid,0,360); colw(sid,3,150)

sheets.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()
# make link-shareable to anyone with the link (viewer)
try: drive.permissions().create(fileId=SID,body={'type':'anyone','role':'reader'}).execute()
except Exception as e: print('share warn',e)
url=drive.files().get(fileId=SID,fields='webViewLink').execute()['webViewLink']
print("SHEET_URL:",url); print("SHEET_ID:",SID)
