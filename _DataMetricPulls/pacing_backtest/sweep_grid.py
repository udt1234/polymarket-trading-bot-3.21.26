# -*- coding: utf-8 -*-
"""PARAMETERIZED seesaw sweep for a grid search. One config per run (JSON as argv[1]). Prints a JSON
result line. NO LOOK-AHEAD (walk-forward priors, data<=t only). Event-driven (tweets+ticks merged).
config keys:
  select : 'pace' (locked Ens+CAP1.5 projection) | 'market' (reverse-pace = price-weighted center)
  nbrk   : 2 | 3    (brackets around the center)
  mode   : 'hold' (winner pays $1) | 'scalp' (sell on +pop, flatten near close)
  conv   : 0 | N    (skip a buy unless round(center) is >=N tweets from the nearest bracket boundary)
  dip,pop,tranche,maxpos,cooldown,gate_h,flat_h : knobs
Scoring: canonical Gamma-confirmed winning_bucket. Data: pmxt YES ticks via bracket_yes_token_ids + X-API tweets."""
import duckdb, sys, glob, os, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
CFG=json.loads(sys.argv[1]) if len(sys.argv)>1 else {}
SELECT=CFG.get('select','pace'); NBRK=int(CFG.get('nbrk',2)); MODE=CFG.get('mode','hold'); CONV=float(CFG.get('conv',0))
DIP=float(CFG.get('dip',0.03)); POP=float(CFG.get('pop',0.05)); TRANCHE=float(CFG.get('tranche',50)); MAXPOS=float(CFG.get('maxpos',500))
COOLDOWN=float(CFG.get('cooldown',180)); GATE_H=float(CFG.get('gate_h',3)); FLAT_H=float(CFG.get('flat_h',2)); EMA_ALPHA=0.02; PROJ_EVERY=120; LABEL=CFG.get('label','base')
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"; OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pts.min()),int(pts.max())
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def bmid(l):
    lo,hi=pbk(l)
    if hi>=10**9: return lo+12.0
    if lo==0: return (hi+1)/2.0
    return (lo+hi)/2.0
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
    ens=(1-cp)*kal+cp*acc; r=(ens-o)/max(rh,.1); return o+min(r,1.5*rmean)*rh
def proj_center(sel,o,eh,rh,rmean,Kk,share,cp,tsec):
    """SELECTION-ONLY projections (Sir OK'd 2026-07-08 to unlock the model for bracket-picking only;
    the LOCKED Ens+CAP1.5 projection itself is untouched - 'pace' below reproduces it)."""
    if eh<1e-6: return o
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))] if share is not None else o*(eh+rh)/eh
    ens=(1-cp)*kal+cp*acc; r=(ens-o)/max(rh,.1)
    if sel=='pace': return o+min(r,1.5*rmean)*rh          # locked baseline
    if sel=='ens_uncap': return ens                       # blend, NO cap
    if sel=='kalman': return kal
    if sel=='accrual': return acc
    if sel=='cap25': return o+min(r,2.5*rmean)*rh
    if sel=='cap3': return o+min(r,3.0*rmean)*rh
    if sel=='linear': return o/eh*(eh+rh)                 # naive current-pace extrapolation
    if sel=='recent': rr=obs(int(tsec)-10800,int(tsec))/3.0; return o+rr*rh   # last-3h burst rate
    return o+min(r,1.5*rmean)*rh
def pickN(center,order,rng,N):
    r=round(center); idx=None
    for i,lab in enumerate(order):
        lo,hi=rng[lab]
        if lo<=r<=hi: idx=i; break
    if idx is None: idx=0 if r<rng[order[0]][0] else len(order)-1
    sel={order[idx]}
    lo,hi=rng[order[idx]]; up=(hi-r)<(r-lo); nxt=[idx+1,idx-1] if up else [idx-1,idx+1]
    for j in nxt:
        if 0<=j<len(order) and len(sel)<N: sel.add(order[j])
    # if still short (edge), extend outward
    step=1
    while len(sel)<N and step<len(order):
        for j in (idx-step,idx+step):
            if 0<=j<len(order): sel.add(order[j])
        step+=1
    return set(list(sel)[:N])
def conv_ok(center,order,rng):
    if CONV<=0: return True
    r=round(center)
    for lab in order:
        lo,hi=rng[lab]
        if lo<=r<=hi:
            d=min(r-lo, hi-r) if hi<10**9 else (r-lo)
            return d>=CONV
    return True

auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True,errors='coerce'); A=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug)
    if not w: continue
    s,e=w; days=(e-s)/86400
    if not 1.5<=days<=2.6 or e>c1 or s<c0+7200: continue
    win=pbk(str(a.winning_bucket))
    if not win: continue
    tok=a.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    if not tok: continue
    A.append({'slug':a.auction_slug,'s':s,'e':e,'win':win,'winlab':str(a.winning_bucket),'final':obs(s,e),'tok':tok})
A=sorted(A,key=lambda x:x['s'])
def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: out+=glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))

rows=[]; hit_in=0; ntr=0
for ai,a in enumerate(A):
    s,e=a['s'],a['e']; total=(e-s)/3600.0; dur_h=48
    priors=[p for p in A if p['e']<s]
    if len(priors)<4: continue
    pr=[p['final']/((p['e']-p['s'])/3600) for p in priors]; rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
    share=share_wf(dur_h,s); fs=pmxt_files(s,e)
    if not fs: continue
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
    tok2lab={str(v):k for k,v in a['tok'].items()}; toklist='('+','.join("'"+str(v)+"'" for v in a['tok'].values())+')'
    px=con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
        WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1
        AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if len(px)<500: continue
    px['lab']=px.aid.map(tok2lab); px['mid']=np.where(px.best_bid>0,(px.best_bid+px.best_ask)/2,px.best_ask)
    order=sorted(a['tok'].keys(), key=lambda l:pbk(l)[0]); rng={l:pbk(l) for l in order}; mids={l:bmid(l) for l in order}
    bfms=bf.ms.to_numpy().astype('int64'); tw=bfms[(bfms>=s*1000)&(bfms<e*1000)]   # MS-native merge
    tp=px.ts.to_numpy().astype('int64'); lab=px.lab.to_numpy(); ask=px.best_ask.to_numpy(float); bid=px.best_bid.to_numpy(float); mid=px.mid.to_numpy(float)
    # concat tweets FIRST so a stable argsort breaks exact-ms ties as tweet-before-price (true causal order)
    ts_all=np.concatenate([tw,tp]); typ=np.concatenate([np.ones(len(tw),np.int8),np.zeros(len(tp),np.int8)]); idxp=np.concatenate([-np.ones(len(tw),int),np.arange(len(tp))])
    o_=np.argsort(ts_all,kind='stable'); ts_all=ts_all[o_]; typ=typ[o_]; idxp=idxp[o_]
    o=0; ema={l:None for l in order}; cmid={l:None for l in order}; bbid={l:0.0 for l in order}; last_buy={l:-10**9 for l in order}
    shares={l:0.0 for l in order}; cost={l:0.0 for l in order}; realized=0.0; dep=0.0; bought_lab=set(); center=None; last_proj=-10**9; targets=set()
    for k in range(len(ts_all)):
        t=int(ts_all[k])
        if typ[k]==1: o+=1
        else:
            i=idxp[k]; l=lab[i]; ema[l]=mid[i] if ema[l] is None else EMA_ALPHA*mid[i]+(1-EMA_ALPHA)*ema[l]; cmid[l]=mid[i]; bbid[l]=bid[i]
        eh=(t/1000.0-s)/3600.0; rh=total-eh; cp=eh/total   # t is MS now
        if eh>=GATE_H and rh>0.2 and (typ[k]==1 or t-last_proj>=PROJ_EVERY*1000 or center is None):
            if SELECT=='market':
                num=sum((cmid[l] or 0)*mids[l] for l in order); den=sum((cmid[l] or 0) for l in order); center=num/den if den>0 else None
            else:
                center=proj_center(SELECT,o,eh,rh,rmean,Kk,share,cp,t/1000.0)
            if center is not None: targets=pickN(center,order,rng,NBRK) if conv_ok(center,order,rng) else set()
            last_proj=t
        if typ[k]==0 and center is not None:
            i=idxp[k]; l=lab[i]; a_=ask[i]; b_=bid[i]
            if MODE=='scalp' and shares[l]>0:
                avg=cost[l]/shares[l]
                if (b_>=avg+POP) or (rh<=FLAT_H):
                    realized+=shares[l]*b_-cost[l]; shares[l]=0.0; cost[l]=0.0
            buyok = eh>=GATE_H and l in targets and ema[l] is not None and a_<=ema[l]-DIP and t-last_buy[l]>=COOLDOWN*1000 and cost[l]+TRANCHE<=MAXPOS
            if MODE=='scalp' and rh<=FLAT_H: buyok=False
            if buyok:
                sh=TRANCHE/a_; shares[l]+=sh; cost[l]+=TRANCHE; dep+=TRANCHE; last_buy[l]=t; bought_lab.add(l)
    if MODE=='hold':
        payoff=sum(shares[l] for l in order if pbk(l)==a['win']); pnl=payoff-dep
    else:
        for l in order:
            if shares[l]>0: realized+=shares[l]*bbid[l]-cost[l]; shares[l]=0.0
        pnl=realized
    if dep>0: ntr+=1; hit_in+= (1 if any(pbk(l)==a['win'] for l in bought_lab) else 0)
    rows.append({'slug':a['slug'].replace('elon-musk-of-tweets-',''),'winner':a['winlab'],'actual':a['final'],
                 'deployed':round(dep),'pnl':round(pnl,1),'roi%':round(100*pnl/dep,1) if dep>0 else 0.0,
                 'winner_bought':bool(any(pbk(l)==a['win'] for l in bought_lab))})

R=pd.DataFrame(rows); tr=R[R.deployed>0]
dep=float(tr.deployed.sum()); pnl=float(tr.pnl.sum())
out={'label':LABEL,'select':SELECT,'nbrk':NBRK,'mode':MODE,'conv':CONV,'dip':DIP,'pop':POP,
     'n_traded':int(len(tr)),'deployed':round(dep),'pnl':round(pnl),
     'pooled_roi_pct':round(100*pnl/dep,2) if dep else 0.0,
     'win_rate_pct':round(100*(tr.pnl>0).mean(),1) if len(tr) else 0.0,
     'median_roi_pct':round(float(tr['roi%'].median()),1) if len(tr) else 0.0,
     'bracket_hit_pct':round(100*hit_in/ntr,1) if ntr else 0.0}
R.to_csv(f"{OUT}/grid_{LABEL}.csv",index=False)
print("GRID_RESULT "+json.dumps(out))
