# -*- coding: utf-8 -*-
"""SEMI-AUTO SEESAW. The human supplies the count read (HUMAN_CENTER) - the one thing the 61% model
can't do. The BOT does the rest, per post, event-driven, no look-ahead:
  1. effective center = the human's read, never below the count already posted.
  2. sigma = sqrt(expected tweets still to come) -> tightens as the auction runs out.
  3. fair price per bracket = normal band around the effective center.
  4. trade the brackets straddling it: BUY when the market is below our fair by >= EDGE (Kelly-sized),
     SELL (take profit) when the market is above our fair by >= EDGE. Hold leftover to resolution.
Kelly sizing: stake = BANKROLL * KELLY_FRACTION * kelly, kelly = (fair-price)/(1-price), shares=stake/price.
Prints a sensitivity: how good does the human's read have to be? Writes trade-by-trade + per-post pace."""
import duckdb, sys, glob, os, json, math, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
SLUG=os.environ.get('AUCTION','elon-musk-of-tweets-april-16-april-18')
HUMAN_CENTER=float(os.environ.get('HUMAN_CENTER','75'))
BANKROLL=5000.0; KELLY_FRACTION=0.25; EDGE=0.02; MAXSTAKE=500.0; CLIP_MAX=40.0; COOLDOWN=15; GATE_H=3.0
SQRT2=math.sqrt(2)
def Phi(x,mu,sd): return 0.5*(1+math.erf((x-mu)/(sd*SQRT2))) if sd>1e-9 else (1.0 if x>=mu else 0.0)
def fairprice(lo,hi,c,sd):
    hh=(hi+0.5) if hi<10**9 else 1e9
    return max(0.0,min(1.0, Phi(hh,c,sd)-Phi(lo-0.5,c,sd)))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug):
    tk=str(slug).replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); bfms=bf.ms.to_numpy().astype('int64')
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
rowa=auc[auc.auction_slug==SLUG].iloc[0]; WIN=str(rowa.winning_bucket); wlo,whi=pbk(WIN)
tok=rowa.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
s,e=noon(SLUG); total=(e-s)/3600.0; finalcount=obs(s,e)
def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: out+=glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))
fs=pmxt_files(s,e); arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
tok2lab={str(v):k for k,v in tok.items()}; toklist='('+','.join("'"+str(v)+"'" for v in tok.values())+')'
px=con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
    WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1 AND best_bid>0
    AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
px['lab']=px.aid.map(tok2lab)
order=sorted(tok.keys(), key=lambda l:pbk(l)[0]); rng={l:pbk(l) for l in order}; idxof={l:i for i,l in enumerate(order)}
tp=px.ts.to_numpy().astype('int64'); lab=px.lab.to_numpy(); ask=px.best_ask.to_numpy(float); bid=px.best_bid.to_numpy(float)
tw=bfms[(bfms>=s*1000)&(bfms<e*1000)]
ts_all=np.concatenate([tw,tp]); typ=np.concatenate([np.ones(len(tw),np.int8),np.zeros(len(tp),np.int8)]); ip=np.concatenate([-np.ones(len(tw),int),np.arange(len(tp))])
o_=np.argsort(ts_all,kind='stable'); ts_all=ts_all[o_]; typ=typ[o_]; ip=ip[o_]

def simulate(human_center, log=False):
    o=0; bka={l:1.0 for l in order}; bkb={l:0.0 for l in order}; shares={l:0.0 for l in order}; cost={l:0.0 for l in order}
    last_tr={l:-10**9 for l in order}; eff=None; sd=None; fair={}; realized=0.0; trades=[]; tweetlog=[]; twn=0; n_tr=0
    for k in range(len(ts_all)):
        t=int(ts_all[k]); eh=(t/1000.0-s)/3600.0; rh=max(total-eh,0.0)
        if typ[k]==1:
            o+=1; twn+=1
            eff=max(human_center,o+1); sd=max(math.sqrt(max(eff-o,1.0)),1.2)
            fair={l:fairprice(rng[l][0],rng[l][1],eff,sd) for l in order}
            if log:
                cb=min(order,key=lambda x:abs((rng[x][0]+rng[x][1])/2-eff))
                tweetlog.append({'tweet_no':twn,'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),
                    'count_so_far':o,'human_center':round(human_center,1),'eff_center':round(eff,1),'sigma':round(sd,1),
                    **{f'fair_{l}':round(fair[l],3) for l in order if abs(idxof[l]-idxof[cb])<=1}})
            continue
        i=ip[k]; l=lab[i]; bka[l]=ask[i]; bkb[l]=bid[i]
        if eff is None or eh<GATE_H or rh<=0.05: continue
        ci=None
        for j,ll in enumerate(order):
            lo,hi=rng[ll]
            if lo<=round(eff)<=hi: ci=j; break
        if ci is None: continue
        if l not in ([order[ci]]+([order[ci+1]] if ci+1<len(order) else [])+([order[ci-1]] if ci>0 else [])): continue
        if t-last_tr[l]<COOLDOWN*1000: continue
        fp=fair.get(l);
        if fp is None: continue
        a=bka[l]; b=bkb[l]
        if fp-a>EDGE and cost[l]<MAXSTAKE and a>0.001:
            kelly=(fp-a)/(1-a); stake=min(BANKROLL*KELLY_FRACTION*kelly, CLIP_MAX, MAXSTAKE-cost[l]); sh=stake/a
            if sh>1e-6:
                shares[l]+=sh; cost[l]+=stake; last_tr[l]=t; n_tr+=1
                if log: trades.append({'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),'action':'BUY','bracket':l,'our_pace':round(eff,1),'pm_odds':round(a,3),'our_fair':round(fp,3)})
        elif b-fp>EDGE and shares[l]>1e-6:
            proceeds=shares[l]*b; realized+=proceeds-cost[l]; last_tr[l]=t; n_tr+=1
            if log: trades.append({'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),'action':'SELL','bracket':l,'our_pace':round(eff,1),'pm_odds':round(b,3),'our_fair':round(fp,3)})
            shares[l]=0.0; cost[l]=0.0
    settle=sum(shares[l]*(1.0 if pbk(l)==(wlo,whi) else 0.0) for l in order); leftcost=sum(cost.values())
    pnl=realized+settle-leftcost
    return pnl,n_tr,trades,tweetlog

print(f"AUCTION {SLUG} | WINNER {WIN} | actual count {finalcount} | your read HUMAN_CENTER={HUMAN_CENTER:.0f}")
print(f"bankroll ${BANKROLL:.0f} | fractional Kelly {KELLY_FRACTION} | edge {EDGE} | max ${MAXSTAKE:.0f}/bracket\n")
print("=== SENSITIVITY: how accurate does YOUR count read have to be? ===")
print(f"{'your read':>10} | {'total P&L':>10} | trades")
for hc in [55,60,65,70,75,80,85,90,95]:
    p,n,_,_=simulate(hc); print(f"{hc:>10.0f} | {p:>+10.2f} | {n}   {'<- actual '+str(finalcount) if abs(hc-finalcount)<3 else ''}")
pnl,n,trades,tweetlog=simulate(HUMAN_CENTER, log=True)
pd.DataFrame(trades).to_csv(f"{OUT}/semi_trades.csv",index=False); pd.DataFrame(tweetlog).to_csv(f"{OUT}/semi_tweets.csv",index=False)
nb=sum(1 for t in trades if t['action']=='BUY'); nsl=sum(1 for t in trades if t['action']=='SELL')
print(f"\n=== YOUR read ({HUMAN_CENTER:.0f}) run: TOTAL P&L ${pnl:+.2f} | trades {n} ({nb} buy, {nsl} sell) ===")
print(f"WROTE semi_trades.csv + semi_tweets.csv")
