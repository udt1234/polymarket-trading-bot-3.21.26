# -*- coding: utf-8 -*-
"""SWEEP: seesaw DIP-BUY on 2 pace-model-selected brackets, across every 2-day Apr-Jun auction.
NO LOOK-AHEAD: the 2 brackets are chosen LIVE from the locked Ens+CAP1.5 pace model (walk-forward
priors, only tweets <= t, only prior auctions for rmean/curve). Event-driven: tweets + every YES
price tick merged in time order. Hold both to resolution; score on the Gamma-confirmed winner.

Answers: does the +66% hold when the winner is NOT the one we loaded up on? And how often does the
pace model even put the winner inside our 2 brackets?
Data: pmxt YES ticks mapped via canonical bracket_yes_token_ids; tweets = X-API backfill (counts_main_feed).
"""
import duckdb, sys, glob, os, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"
PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"; OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
DIP=0.03; TRANCHE=50.0; COOLDOWN=180; MAXPOS=500.0; EMA_ALPHA=0.02; GATE_H=3.0; PROJ_EVERY=120   # knobs

# ---- tweets (locked pace-model inputs) ----
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pts.min()),int(pts.max())
hd_all=pd.to_datetime(pts,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug):
    try:
        tk=str(slug).replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
    except Exception: return None
_sc={}
def share_wf(dur_h,before_ts):
    if (dur_h,before_ts) in _sc: return _sc[(dur_h,before_ts)]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None; _sc[(dur_h,before_ts)]=r; return r
def ens_cap15(o,eh,rh,rmean,Kk,share,cp):
    if eh<1e-6: return o
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))] if share is not None else o*(eh+rh)/eh
    ens=(1-cp)*kal+cp*acc
    r=(ens-o)/max(rh,.1); return o+min(r,1.5*rmean)*rh   # LOCKED Ens+CAP1.5

# ---- auctions ----
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True,errors='coerce')
A=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug)
    if not w: continue
    s,e=w; days=(e-s)/86400
    if not 1.5<=days<=2.6: continue
    if e>c1 or s<c0+7200: continue
    win=pbk(str(a.winning_bucket));
    if not win: continue
    tok=a.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    if not tok: continue
    A.append({'slug':a.auction_slug,'s':s,'e':e,'win':win,'winlab':str(a.winning_bucket),'final':obs(s,e),'tok':tok})
A=sorted(A,key=lambda x:x['s'])
print(f"sweep set: {len(A)} two-day auctions Apr-Jun (all Gamma-resolved, all tweet-covered)")

def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end:
        out+=glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))

def pick2(P,order,rng):
    """given projection P and sorted bracket labels 'order' with ranges rng[lab]=(lo,hi): the bracket
    containing round(P) + the neighbor P leans toward. Returns set of 2 labels (or 1 at the edge)."""
    r=round(P); idx=None
    for i,lab in enumerate(order):
        lo,hi=rng[lab]
        if lo<=r<=hi: idx=i; break
    if idx is None:  # P beyond all ranges -> clamp to nearest end
        idx=0 if r<rng[order[0]][0] else len(order)-1
    lo,hi=rng[order[idx]]; up = (hi-r) < (r-lo)   # nearer the top -> lean up
    j = idx+1 if up else idx-1
    if j<0: j=idx+1
    if j>=len(order): j=idx-1
    return {order[idx], order[max(0,min(len(order)-1,j))]}

allrows=[]; allbuys=[]
for ai,a in enumerate(A):
    s,e=a['s'],a['e']; total=(e-s)/3600.0; dur_h=48; act=a['final']
    priors=[p for p in A if p['e']<s]
    if len(priors)<4: continue   # need >=4 prior 2-day auctions for walk-forward rmean/Kk
    pr=[p['final']/((p['e']-p['s'])/3600) for p in priors]; rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
    share=share_wf(dur_h,s)
    # price ticks (YES) for this auction, mapped via tokens
    fs=pmxt_files(s,e)
    if not fs: continue
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
    tok2lab={str(v):k for k,v in a['tok'].items()}
    toklist='('+','.join("'"+str(v)+"'" for v in a['tok'].values())+')'
    px=con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
        WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1
        AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if len(px)<500: continue
    px['lab']=px.aid.map(tok2lab); px['mid']=np.where(px.best_bid>0,(px.best_bid+px.best_ask)/2,px.best_ask)
    order=sorted(a['tok'].keys(), key=lambda l:pbk(l)[0]); rng={l:pbk(l) for l in order}
    # event stream: tweets(in window) + price ticks
    tw=pts[(pts>=s)&(pts<e)]
    tp=(px.ts.to_numpy()//1000).astype('int64'); lab=px.lab.to_numpy(); ask=px.best_ask.to_numpy(float); mid=px.mid.to_numpy(float)
    ts_all=np.concatenate([tp,tw]); typ=np.concatenate([np.zeros(len(tp),np.int8),np.ones(len(tw),np.int8)]); idxp=np.concatenate([np.arange(len(tp)),-np.ones(len(tw),int)])
    o_=np.argsort(ts_all,kind='stable'); ts_all=ts_all[o_]; typ=typ[o_]; idxp=idxp[o_]
    o=0; ema={l:None for l in order}; bookask={l:1.0 for l in order}; last_buy={l:-10**9 for l in order}
    shares={l:0.0 for l in order}; cost={l:0.0 for l in order}; P=None; last_proj=-10**9; targets=set()
    for k in range(len(ts_all)):
        t=int(ts_all[k])
        if typ[k]==1:
            o+=1
        else:
            i=idxp[k]; l=lab[i]; a_=ask[i]; m=mid[i]
            ema[l]=m if ema[l] is None else EMA_ALPHA*m+(1-EMA_ALPHA)*ema[l]; bookask[l]=a_
        eh=(t-s)/3600.0; rh=total-eh; cp=eh/total
        if eh>=GATE_H and rh>0.2 and (typ[k]==1 or t-last_proj>=PROJ_EVERY or P is None):
            P=ens_cap15(o,eh,rh,rmean,Kk,share,cp); targets=pick2(P,order,rng); last_proj=t
        if typ[k]==0 and eh>=GATE_H and P is not None:
            l=lab[idxp[k]]
            if l in targets and ema[l] is not None and ask[idxp[k]]<=ema[l]-DIP and t-last_buy[l]>=COOLDOWN and cost[l]+TRANCHE<=MAXPOS:
                a_=ask[idxp[k]]; sh=TRANCHE/a_; shares[l]+=sh; cost[l]+=TRANCHE; last_buy[l]=t
                allbuys.append({'slug':a['slug'],'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'hrs_to_close':round((e-t)/3600,2),
                    'proj':round(P,1),'bracket':l,'buy_price':round(a_,3),'won':'WIN' if pbk(l)==a['win'] else 'lose'})
    tot_cost=sum(cost.values()); payoff=sum(shares[l] for l in order if pbk(l)==a['win']); pnl=payoff-tot_cost
    winner_in_targets = any(pbk(l)==a['win'] for l in cost if cost[l]>0)
    held=[l for l in order if cost[l]>0]
    allrows.append({'#':ai,'slug':a['slug'].replace('elon-musk-of-tweets-',''),'winner':a['winlab'],'actual':act,
        'brackets_bought':'+'.join(held),'winner_bought':'YES' if winner_in_targets else 'no',
        'deployed':round(tot_cost),'payoff':round(payoff),'pnl':round(pnl),'roi%':round(100*pnl/tot_cost,1) if tot_cost else 0.0,'nbuys':sum(1 for b in allbuys if b['slug']==a['slug'])})
    print(f"  {a['slug'].replace('elon-musk-of-tweets-',''):<26} win {a['winlab']:<8} act {act:>3} | bought {('+'.join(held)) or '(none)':<20} winner? {'YES' if winner_in_targets else 'no ':<3} | ${round(tot_cost):>4} -> ${round(payoff):>4} | P&L ${round(pnl):>+5} ({round(100*pnl/tot_cost,1) if tot_cost else 0:+.0f}%)")

R=pd.DataFrame(allrows); B=pd.DataFrame(allbuys)
R.to_csv(f"{OUT}/sweep_seesaw_auctions.csv",index=False); B.to_csv(f"{OUT}/sweep_seesaw_buys.csv",index=False)
traded=R[R.deployed>0]
print("\n=== SWEEP SUMMARY (pace-model bracket pick, no look-ahead, event-driven) ===")
print(f"auctions traded: {len(traded)} | total deployed ${traded.deployed.sum():,.0f} | total P&L ${traded.pnl.sum():,.0f} | pooled ROI {100*traded.pnl.sum()/traded.deployed.sum():+.1f}%")
print(f"win-rate (auctions with +P&L): {100*(traded.pnl>0).mean():.0f}% ({(traded.pnl>0).sum()}/{len(traded)}) | median auction ROI {traded['roi%'].median():+.1f}%")
print(f"winner landed in our 2 brackets: {100*(traded.winner_bought=='YES').mean():.0f}% of traded auctions  <- the pace model's real job")
print(f"mean ROI when winner WAS in our brackets: {traded[traded.winner_bought=='YES']['roi%'].mean():+.1f}% | when NOT: {traded[traded.winner_bought=='no']['roi%'].mean():+.1f}%")
print(f"\nWROTE {OUT}/sweep_seesaw_auctions.csv  and  sweep_seesaw_buys.csv")
