# -*- coding: utf-8 -*-
"""ONE auction. ONE strategy. The SEESAW, active, trade-by-trade.
Per POST we recompute our center (pace) and turn it into a FAIR price for each bracket (a normal
distribution around the projected final count, tightening as time runs out). Then, tick by tick, we
BUY a bracket whenever the market is cheaper than our fair by >= EDGE, and SELL it whenever the market
is richer than our fair by >= EDGE. As our per-post center moves and the market oscillates around it,
this fires the hundreds of back-and-forth trades Sir expects. Hold leftover to resolution (winner=$1).
Event-driven ms (tweets + every price tick). NO look-ahead: center uses tweets<=t; fills at market price at t."""
import duckdb, sys, glob, os, json, math, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
SLUG=os.environ.get('AUCTION','elon-musk-of-tweets-april-16-april-18')
EDGE=0.02; UNIT=20.0; MAXINV=300.0; COOLDOWN=15; GATE_H=3.0; SIGMA_MAX=100.0    # strategy knobs (SIGMA_MAX relaxed: calibrated sigma is ~9-40, the old 8 gate would block all trading)
REACT6H=os.environ.get('REACT6H','0')=='1'; REBUY_DELAY=300; PACE_EDGE=os.environ.get('PACE_EDGE','1')=='1'   # item3 reworked: rebuy short after 5min; buy the PACE bracket (edge-gated unless PACE_EDGE=0)
LAST_H=float(os.environ.get('LAST_H','999'))   # only trade when hours-to-close <= LAST_H (999 = no gate, default/locked behavior)
SQRT2=math.sqrt(2)
def Phi(x,mu,sd): return 0.5*(1+math.erf((x-mu)/(sd*SQRT2))) if sd>1e-9 else (1.0 if x>=mu else 0.0)
def fairprice(lo,hi,center,sd):
    hh = (hi+0.5) if hi<10**9 else 1e9
    return max(0.0,min(1.0, Phi(hh,center,sd)-Phi(lo-0.5,center,sd)))
# CALIBRATED sigma (Sir 2026-07-11): our old formula was ~40-50% of the REAL forecast error measured
# across 62 historical 2-day auctions (final - Ens+Cap1.5 center). These are the measured residual stds
# by hours-remaining -> honest, wide odds. Fixes the 84%-at-24h / 100%-at-4h overconfidence.
_SIG_RH=[1,4,8,12,18,24,32,40,48]; _SIG_SD=[5.0,7.8,10.8,15.5,16.8,18.9,31.4,38.2,42.0]
def calib_sigma(rh): return max(float(np.interp(rh,_SIG_RH,_SIG_SD)),1.0)
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
pts=(bf.ms.to_numpy()//1000).astype('int64'); bfms=bf.ms.to_numpy().astype('int64'); c0=int(pts.min())
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
_sc={}
def share_wf(dur_h,before_ts):
    if (dur_h,before_ts) in _sc: return _sc[(dur_h,before_ts)]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None; _sc[(dur_h,before_ts)]=r; return r
def center_ens_cap15(o,eh,rh,rmean,Kk,share,cp):
    if eh<1e-6: return float(o)
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))] if share is not None else o*(eh+rh)/eh
    ens=(1-cp)*kal+cp*acc; r=(ens-o)/max(rh,.1); return o+min(r,1.5*rmean)*rh
def models_all(o,eh,rh,rmean,Kk,share,cp):   # identical math to center_ens_cap15; also returns the sub-models for audit logging
    if eh<1e-6: return float(o),float(o),float(o),float(o)
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))] if share is not None else o*(eh+rh)/eh
    ens=(1-cp)*kal+cp*acc; r=(ens-o)/max(rh,.1); return kal,acc,ens,o+min(r,1.5*rmean)*rh
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
row=auc[auc.auction_slug==SLUG].iloc[0]; WIN=str(row.winning_bucket); wlo,whi=pbk(WIN)
tok=row.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
s,e=noon(SLUG); total=(e-s)/3600.0
allA=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    try: w=noon(a.auction_slug)
    except Exception: w=None
    if not w or not 1.5<=(w[1]-w[0])/86400<=2.6: continue
    allA.append({'s':w[0],'e':w[1],'final':obs(w[0],w[1])})
pr=[a['final']/((a['e']-a['s'])/3600) for a in allA if a['e']<s]
rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5)); share=share_wf(48,s)
finalcount=obs(s,e)
print(f"AUCTION {SLUG} | {datetime.fromtimestamp(s,ET):%m-%d %H:%M}->{datetime.fromtimestamp(e,ET):%m-%d %H:%M} ET | WINNER {WIN} | actual count {finalcount} | baseline {rmean:.1f}/h")
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
_have=set(px.lab.dropna().unique()); _missing=[l for l in order if l not in _have]   # DATA-COVERAGE GUARD (2026-07-11 lesson)
if _missing: print(f"WARNING: {len(_missing)}/{len(order)} bracket(s) have NO pmxt price data: {_missing}"+("  <-- INCLUDES THE WINNER; results are INVALID" if WIN in _missing else ""))
tp=px.ts.to_numpy().astype('int64'); lab=px.lab.to_numpy(); ask=px.best_ask.to_numpy(float); bid=px.best_bid.to_numpy(float)
tw=bfms[(bfms>=s*1000)&(bfms<e*1000)]
ts_all=np.concatenate([tw,tp]); typ=np.concatenate([np.ones(len(tw),np.int8),np.zeros(len(tp),np.int8)]); ip=np.concatenate([-np.ones(len(tw),int),np.arange(len(tp))])
o_=np.argsort(ts_all,kind='stable'); ts_all=ts_all[o_]; typ=typ[o_]; ip=ip[o_]
o=0; bka={l:1.0 for l in order}; bkb={l:0.0 for l in order}
shares={l:0.0 for l in order}; cost={l:0.0 for l in order}; last_tr={l:-10**9 for l in order}; last_o={l:-1 for l in order}
held={l:False for l in order}; no_rebuy_until={l:0 for l in order}
center=None; sd=None; fair={}; realized=0.0; trades=[]; tweetlog=[]; twn=0; last_recomp=-10**9; curk=cura=cure=None
for k in range(len(ts_all)):
    t=int(ts_all[k]); eh=(t/1000.0-s)/3600.0; rh=max(total-eh,0.0); cp=eh/total if total else 0
    if typ[k]==1:
        o+=1; twn+=1; cprev=center
        if eh>=0.5:
            curk,cura,cure,center=models_all(o,eh,rh,rmean,Kk,share,cp)
            # HONEST sigma (per Sir's #1: believe the per-post pace only when it's actually certain).
            # remaining-Poisson sd  +  rate-estimate uncertainty extrapolated over remaining hours.
            # huge early (few tweets, long window) -> fair prices go flat -> no early trades; ~1-2 near close.
            sd=calib_sigma(rh)
            fair={l:fairprice(rng[l][0],rng[l][1],center,sd) for l in order}; last_recomp=t
            cb=min(order,key=lambda x:abs((rng[x][0]+rng[x][1])/2-center)) if center else order[0]
            tweetlog.append({'tweet_no':twn,'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),
                'count_so_far':o,'center_before':round(cprev,1) if cprev else '','center_after':round(center,1),
                'per_post_move':round(center-cprev,2) if cprev else '','sigma':round(sd,1),
                **{f'fair_{l}':round(fair[l],3) for l in order if abs(idxof[l]-idxof[cb])<=1}})
        if REACT6H and rh<=6.0 and center is not None and fair:   # ITEM 3: last-6h tweet-reaction overlay
            ci2=None
            for j2,ll2 in enumerate(order):
                lo2,hi2=rng[ll2]
                if lo2<=round(center)<=hi2: ci2=j2; break
            if ci2 is not None:
                early=order[ci2-1] if ci2>0 else None; pace=order[ci2]
                if early and shares[early]>1e-6:   # he posted -> SHORT/early bracket plummets -> dump it now at the bid
                    b=bkb[early]; realized+=shares[early]*b-cost[early]
                    trades.append({'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),'action':'SELL-EARLY','bracket':early,'price':round(b,3),'our_fair':round(fair.get(early,0),3),'edge':0,'our_center':round(center,1),'shares':round(shares[early],1),'inv_$':0,'rpnl':round(shares[early]*b-cost[early],2),'held':False,'kal':round(curk,1) if curk is not None else '','acc':round(cura,1) if cura is not None else '','ens':round(cure,1) if cure is not None else ''})
                    shares[early]=0.0; cost[early]=0.0; last_o[early]=o; no_rebuy_until[early]=t+REBUY_DELAY*1000
                if pace and bka[pace]<1.0 and (not PACE_EDGE or (fair.get(pace,0)-bka[pace])>EDGE):   # buy the PACE bracket (jumps or holds), HOLD to resolution
                    sh=UNIT/bka[pace]; shares[pace]+=sh; cost[pace]+=UNIT; held[pace]=True; last_o[pace]=o
                    trades.append({'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),'action':'BUY-HOLD-PACE','bracket':pace,'price':round(bka[pace],3),'our_fair':round(fair.get(pace,0),3),'edge':round(fair.get(pace,0)-bka[pace],3),'our_center':round(center,1),'shares':round(sh,1),'inv_$':round(cost[pace]),'rpnl':0,'held':True,'kal':round(curk,1) if curk is not None else '','acc':round(cura,1) if cura is not None else '','ens':round(cure,1) if cure is not None else ''})
        continue
    i=ip[k]; l=lab[i]; bka[l]=ask[i]; bkb[l]=bid[i]
    # RECOMPUTE the pace on the clock (every 60s), not just on tweets -> projection decays as time runs
    # down during quiet stretches, so late edges keep firing (trades continue to the close).
    if eh>=0.5 and t-last_recomp>=60000:
        curk,cura,cure,center=models_all(o,eh,rh,rmean,Kk,share,cp)
        sd=calib_sigma(rh)
        fair={l2:fairprice(rng[l2][0],rng[l2][1],center,sd) for l2 in order}; last_recomp=t
    if center is None or eh<GATE_H or rh<=0.05 or rh>LAST_H: continue   # LAST_H gate: skip until inside the last LAST_H hours
    if sd is None or sd>SIGMA_MAX: continue   # only trade when the per-post pace is TRUSTWORTHY (certain)
    ci=None
    for j,ll in enumerate(order):
        lo,hi=rng[ll]
        if lo<=round(center)<=hi: ci=j; break
    if ci is None: continue
    targets=[order[ci]]+([order[ci+1]] if ci+1<len(order) else [])+([order[ci-1]] if ci>0 else [])
    if l not in targets or o<=last_o[l]: continue   # CAP: max 1 trade per bracket per tweet (Sir 2026-07-09)
    fp=fair.get(l)
    if fp is None: continue
    if bka[l] < fp-EDGE and t>=no_rebuy_until.get(l,0):   # no cap; early bracket rebuy waits out the post plummet
        sh=UNIT/bka[l]; shares[l]+=sh; cost[l]+=UNIT; last_tr[l]=t; last_o[l]=o
        trades.append({'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),'action':'BUY','bracket':l,
            'price':round(bka[l],3),'our_fair':round(fp,3),'edge':round(fp-bka[l],3),'our_center':round(center,1),'shares':round(sh,1),'inv_$':round(cost[l]),'rpnl':0,'held':False,'kal':round(curk,1) if curk is not None else '','acc':round(cura,1) if cura is not None else '','ens':round(cure,1) if cure is not None else ''})
    elif bkb[l] > fp+EDGE and shares[l]>1e-6 and not (held.get(l) and rh<=6.0):   # hold the long bracket in the last 6h
        sh=min(UNIT/bkb[l],shares[l]); proceeds=sh*bkb[l]; frac=sh/shares[l]; c=cost[l]*frac
        realized+=proceeds-c; shares[l]-=sh; cost[l]-=c; last_tr[l]=t; last_o[l]=o
        trades.append({'et':datetime.fromtimestamp(t/1000,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round(rh,2),'action':'SELL','bracket':l,
            'price':round(bkb[l],3),'our_fair':round(fp,3),'edge':round(bkb[l]-fp,3),'our_center':round(center,1),'shares':round(sh,1),'inv_$':round(cost[l]),'rpnl':round(proceeds-c,2),'held':False,'kal':round(curk,1) if curk is not None else '','acc':round(cura,1) if cura is not None else '','ens':round(cure,1) if cure is not None else ''})
for l in order:   # RESOLUTION: book held/unsold positions at their $1/$0 payout so Running P&L is complete
    if shares[l]>1e-6:
        pay=1.0 if pbk(l)==(wlo,whi) else 0.0
        trades.append({'et':datetime.fromtimestamp(e,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':0.0,'action':'RESOLUTION','bracket':l,'price':round(pay,3),'our_fair':round(pay,3),'edge':0,'our_center':round(center,1) if center else '','shares':round(shares[l],1),'inv_$':round(cost[l]),'rpnl':round(shares[l]*pay-cost[l],2),'held':bool(held.get(l,False)),'kal':round(curk,1) if curk is not None else '','acc':round(cura,1) if cura is not None else '','ens':round(cure,1) if cure is not None else ''})
settle=sum(shares[l]*(1.0 if pbk(l)==(wlo,whi) else 0.0) for l in order); leftcost=sum(cost.values())
pnl=realized+settle-leftcost
SUF='_react' if REACT6H else ''; T=pd.DataFrame(trades); T.to_csv(f"{OUT}/one_auction_trades{SUF}.csv",index=False); pd.DataFrame(tweetlog).to_csv(f"{OUT}/one_auction_tweets.csv",index=False)
nb=int((T.action=='BUY').sum()) if len(T) else 0; nsl=int((T.action=='SELL').sum()) if len(T) else 0
print(f"\n=== SEESAW on ONE auction ===")
print(f"tweets in window: {twn} | TOTAL TRADES: {len(T)}  ({nb} buys, {nsl} sells)")
print(f"realized ${realized:+.2f} | settle leftover ${settle-leftcost:+.2f} | TOTAL P&L ${pnl:+.2f}")
print(f"WROTE one_auction_trades.csv ({len(T)} rows) + one_auction_tweets.csv ({len(tweetlog)} rows)")
