"""Trade-the-edge simulation (v1). For each auction, walk a 30-min grid over the market's life;
at each step compute each brain's WORTH per bracket from tweets-so-far, compare to the REAL CLOB
price, and run the convergence rule: BUY when worth-price > gap, SELL when price reverts to worth.
Open positions close at resolution. Reports $ PnL per model vs holding the market. Hawkes excluded
(too slow + worst forecaster)."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'; OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
ET = ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
BUY_GAP=0.05; GRID_MIN=30
MODELS=['Linear','CurBayes','M0','Decay','M4MMPP','Kalman']  # M1Seas dropped (slow loop), Hawkes dropped (worst)

bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms')
post_ts=(bf.ms.to_numpy()//1000).astype('int64')
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))

prc=pd.read_parquet(OUT/'clob_prices.parquet')
price_idx={}
for (sl,bk),g in prc.sort_values('t').groupby(['auction_slug','bucket']):
    price_idx[(sl,bk)]=(g['t'].to_numpy(),g['price'].to_numpy())
def price_at(sl,bk,t):
    a=price_idx.get((sl,bk))
    if a is None: return None
    ts,ps=a; i=np.searchsorted(ts,t,side='right')-1
    if i<0: return None
    v=float(ps[i]); return v if 0<v<1 else None

auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def noonET(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()]; d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()]; d2=int(tk[3])
        else: mo2=mo1; d2=int(tk[2])
    except: return None
    y2=yr+(1 if mo2<mo1 else 0)
    return (int(pd.Timestamp(datetime(yr,mo1,d1,12,0,tzinfo=ET)).timestamp()),
            int(pd.Timestamp(datetime(y2,mo2,d2,12,0,tzinfo=ET)).timestamp()))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),None)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(pred,sig,lo,hi):
    sig=max(sig,1.0); zl=(lo-0.5-pred)/sig
    return max(0.0,1-ncdf(zl)) if hi is None else max(0.0,ncdf((hi+0.5-pred)/sig)-ncdf(zl))

# fast models
def Linear(o,eh,rh): return 0 if eh<=0 else o*(eh+rh)/eh
def CurBayes(o,eh,rh,pool):
    th=eh+rh
    if not pool or o<=0 or eh<=0: return float(np.mean(pool)) if pool else 0
    ec=min(0.99,max(0.001,eh/th));op=o/ec;pm=float(np.mean(pool));ps=max(1.0,float(np.std(pool,ddof=1)) if len(pool)>1 else pm*0.25)
    ov=max(1.0,o*(1-ec)/(ec**2));return (pm/ps**2+op/ov)/(1/ps**2+1/ov)
def M0(o,eh,rh,pt,pd_):
    if not pt: return o*(eh+rh)/max(eh,1)
    return o+(sum(pt)+o)/(sum(pd_)+eh)*rh if (sum(pd_)+eh)>0 else o
def Decay(o,eh,rh,pwa,eps=0.85):
    if not pwa: return o*(eh+rh)/max(eh,1)
    a0=sum(t*eps**ag for t,_,ag in pwa);b0=sum(d*eps**ag for _,d,ag in pwa) or 1;return o+(a0+o)/(b0+eh)*rh
def M4MMPP(o,eh,rh,rates):
    if not rates: return o*(eh+rh)/max(eh,1)
    return o+(0.5*(o/max(eh,1))+0.5*float(np.mean(rates)))*rh
def Kalman(o,eh,rh,rates):
    if not rates: return o*(eh+rh)/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;R=max(0.1,P*0.5);K=(P+0.01)/(P+0.01+R);return o+(x+K*(o/max(eh,1)-x))*rh
def M1Seas(o,eh,rh,sm,cur,dflt):
    if not sm: return o*(eh+rh)/max(eh,1)
    er=sum(sm.get((pd.Timestamp(cur+h*3600,unit='s',tz='UTC').tz_convert('America/New_York').dayofweek,
                    pd.Timestamp(cur+h*3600,unit='s',tz='UTC').tz_convert('America/New_York').hour),dflt) for h in range(int(rh)))
    return o+er

# build selection
sel=[]
cur=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')
        &(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
for _,a in cur.iterrows():
    if a.auction_slug not in {s for s,_ in [(k[0],0) for k in price_idx]}: pass
    w=noonET(a.auction_slug,a['start_utc'].year)
    if not w: continue
    ns,ne=w; dur=a.duration_type
    if dur=='7-day' and ns<int(pd.Timestamp('2025-09-05',tz='UTC').timestamp()): continue
    if dur=='2-day' and ns<int(pd.Timestamp('2026-01-05',tz='UTC').timestamp()): continue
    import json as _j
    try: tokmap=_j.loads(a['bracket_yes_token_ids'])
    except: continue
    blab=list(tokmap.keys())
    if not any((a.auction_slug,b) in price_idx for b in blab): continue
    a_=obs(ns,ne)
    if a_<=0: continue
    sel.append(dict(slug=a.auction_slug,dur=dur,ns=ns,ne=ne,winner=a['winning_bucket'],
                    branges=[(b,pbk(b)) for b in blab if pbk(b)],actual=a_))
sel=sorted(sel,key=lambda x:x['ns'])
print(f"auctions in sim: {len(sel)} (7d={sum(1 for x in sel if x['dur']=='7-day')}, 2d={sum(1 for x in sel if x['dur']=='2-day')})")

err_hist={m:[] for m in MODELS}
res=[]
for a in sel:
    ns,ne,winner=a['ns'],a['ne'],a['winner']; total_h=(ne-ns)/3600
    priors=[p for p in sel if p['ne']<ns]
    pt=[p['actual'] for p in priors]; pdur=[(p['ne']-p['ns'])/3600 for p in priors]
    prate=[p['actual']/((p['ne']-p['ns'])/3600) for p in priors if p['ne']>p['ns']]
    pwa=[(p['actual'],(p['ne']-p['ns'])/3600,(ns-p['ne'])/604800) for p in priors]
    sm={};dflt=float(np.mean(prate)) if prate else 1.0
    hi=np.searchsorted(post_ts,ns)
    if hi>100:
        hd=pd.to_datetime(post_ts[:hi],unit='s',utc=True).tz_convert('America/New_York')
        c=pd.DataFrame({'dow':hd.dayofweek,'hour':hd.hour}).groupby(['dow','hour']).size();span=max(1,(ns-post_ts[0])/86400)
        for (dw,hr),cc in c.items(): sm[(dw,hr)]=cc/(span/7)
    sig={m:(float(np.std(err_hist[m])) if len(err_hist[m])>=5 else 15.0) for m in MODELS}
    # trading grid (only where prices exist)
    tmin=min((price_idx[(a['slug'],b)][0][0] for b,_ in a['branges'] if (a['slug'],b) in price_idx), default=ns)
    tmax=max((price_idx[(a['slug'],b)][0][-1] for b,_ in a['branges'] if (a['slug'],b) in price_idx), default=ne)
    t0=max(ns,tmin); t1=min(ne,tmax)
    pos={m:{} for m in MODELS}; pnl={m:0.0 for m in MODELS}; ntr={m:0 for m in MODELS}
    t=t0
    while t<t1:
        o=obs(ns,t); eh=(t-ns)/3600; rh=(ne-t)/3600
        if eh>0.2:
            preds={'Linear':Linear(o,eh,rh),'CurBayes':CurBayes(o,eh,rh,pt),'M0':M0(o,eh,rh,pt,pdur),
                   'Decay':Decay(o,eh,rh,pwa),'M4MMPP':M4MMPP(o,eh,rh,prate),'Kalman':Kalman(o,eh,rh,prate)}
            for m in MODELS:
                pred=preds[m]; worth={b:bprob(pred,sig[m],lo,hi) for b,(lo,hi) in a['branges']}
                tot=sum(worth.values()) or 1; worth={b:v/tot for b,v in worth.items()}
                for b,_ in a['branges']:
                    pr=price_at(a['slug'],b,t)
                    if pr is None: continue
                    held=pos[m].get(b)
                    if held is None and worth[b]-pr>BUY_GAP and pr>0.02:
                        pos[m][b]=pr
                    elif held is not None and pr>=worth[b]:
                        pnl[m]+=pr-held; ntr[m]+=1; pos[m][b]=None
        t+=GRID_MIN*60
    for m in MODELS:
        for b,entry in pos[m].items():
            if entry is not None:
                pnl[m]+=(1.0 if b==winner else 0.0)-entry; ntr[m]+=1
    res.append(dict(slug=a['slug'],dur=a['dur'],**{f'pnl_{m}':pnl[m] for m in MODELS},**{f'ntr_{m}':ntr[m] for m in MODELS}))
    # walk-forward error signal: each model's T-1d-equivalent forecast error this auction
    tref=ne-86400; oref=obs(ns,tref); ehr=(tref-ns)/3600
    if ehr>0.2:
        refp={'Linear':Linear(oref,ehr,24.0),'CurBayes':CurBayes(oref,ehr,24.0,pt),'M0':M0(oref,ehr,24.0,pt,pdur),
              'Decay':Decay(oref,ehr,24.0,pwa),'M4MMPP':M4MMPP(oref,ehr,24.0,prate),'Kalman':Kalman(oref,ehr,24.0,prate)}
        for m in MODELS: err_hist[m].append(a['actual']-refp[m])

R=pd.DataFrame(res)
print("\n=== TRADE-THE-EDGE PnL (avg $ per auction, 1 share/trade) ===")
print(f"{'Model':<10}{'7d $/auc':>10}{'7d trades':>10}{'2d $/auc':>10}{'2d trades':>10}{'ALL $/auc':>11}")
rows=[]
for m in MODELS:
    s7=R[R.dur=='7-day']; s2=R[R.dur=='2-day']
    rows.append((m, s7[f'pnl_{m}'].mean(), s7[f'ntr_{m}'].mean(), s2[f'pnl_{m}'].mean(), s2[f'ntr_{m}'].mean(), R[f'pnl_{m}'].mean()))
for m,a7,n7,a2,n2,al in sorted(rows,key=lambda x:-x[5]):
    print(f"{m:<10}{a7:>10.3f}{n7:>10.1f}{a2:>10.3f}{n2:>10.1f}{al:>11.3f}")
R.to_csv(OUT/'trade_sim_results.csv',index=False)
print(f"\nsaved {OUT/'trade_sim_results.csv'}")
