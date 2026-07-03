"""Layered / recency pacing test. Obeys BACKTEST_RULES.md: decide on data <= cps, outcome only
for scoring, walk-forward priors + diurnal + share curves, benchmarked vs the MARKET, hit-rates
reported with 95% CIs (so we don't over-read small gaps).
  Q1 recency-Kalman: K_recent (EWMA recent rate), K_recent_sleep (deseasonalized EWMA x diurnal-
     weighted remaining hours, so recent silence + sleep both lower the projection).
  Q2 Kalman+PF layered: Ens_KPF = average of K_base and Particle-Filter bracket-prob vectors.
  Q3 full layer: Ens_All = average of K_base + K_recent_sleep + Accrual + PF.
Equal-n head-to-head: a checkpoint is scored only when the market price also exists."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8'); rng=np.random.default_rng(11)
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON=ROOT/'_DataMetricPulls'/'canonical'; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms')
pt=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pt.min()),int(pt.max())
def obs(s,e): return int(np.searchsorted(pt,e)-np.searchsorted(pt,s))
def hourly_counts(s,e):
    n=int((e-s)/3600)
    if n<=0: return np.array([]),np.array([])
    bounds=s+np.arange(n+1)*3600; idx=np.searchsorted(pt,bounds); cnts=np.diff(idx).astype(float)
    ets=pd.to_datetime(bounds[:-1],unit='s',utc=True).tz_convert(ET).hour.to_numpy()
    return cnts,ets

hd_all=pd.to_datetime(pt,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
_mc={}
def diurnal_mult(before_s):
    if before_s in _mc: return _mc[before_s]
    h=hd_all[pt<before_s]
    if len(h)<240: r=np.ones(24)
    else:
        m=np.array([np.sum(h==hh) for hh in range(24)],float); r=m/m.mean() if m.mean()>0 else np.ones(24)
    _mc[before_s]=r; return r
_sc={}
def share_wf(dur_h,before_ts):
    k=(dur_h,before_ts)
    if k in _sc: return _sc[k]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None
    _sc[k]=r; return r

def ewma_rate(s,cps,hl=8.0):
    cnts,_=hourly_counts(s,cps); n=len(cnts)
    if n==0: return None
    w=0.5**((n-1-np.arange(n))/hl); return float(np.sum(cnts*w)/np.sum(w))
def ewma_deseason(s,cps,mult,hl=8.0):
    cnts,ets=hourly_counts(s,cps); n=len(cnts)
    if n==0: return None
    rates=cnts/np.maximum(mult[ets],0.15); w=0.5**((n-1-np.arange(n))/hl); return float(np.sum(rates*w)/np.sum(w))
def eff_remaining(cps,e,mult):
    n=int((e-cps)/3600)
    if n<=0: return 0.0
    hrs=pd.to_datetime(cps+np.arange(n)*3600,unit='s',utc=True).tz_convert(ET).hour.to_numpy(); return float(np.sum(mult[hrs]))

def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(pred,sig,lo,hi):
    sig=max(sig,1.0); zl=(lo-0.5-pred)/sig
    return max(1e-9,(1-ncdf(zl)) if hi is None else (ncdf((hi+0.5-pred)/sig)-ncdf(zl)))

M=600
def pf_probs(s,cps,e,prior_rate,mult,branges):
    cnts,ets=hourly_counts(s,cps)
    lam=rng.lognormal(math.log(max(prior_rate,0.2)),0.6,M)
    for nn,H in zip(cnts,ets):
        lam*=np.exp(rng.normal(0,0.12,M)); mu=np.maximum(lam*mult[H],1e-4); logw=nn*np.log(mu)-mu
        w=np.exp(logw-logw.max()); w/=w.sum(); idx=rng.choice(M,M,p=w); lam=lam[idx]*np.exp(rng.normal(0,0.03,M))
    nrem=int((e-cps)/3600)
    rm=float(np.sum(mult[pd.to_datetime(cps+np.arange(nrem)*3600,unit='s',utc=True).tz_convert(ET).hour.to_numpy()])) if nrem>0 else 0.0
    o=obs(s,cps); finals=o+rng.poisson(np.clip(lam*rm,0,1e4))
    return {b:float(((finals>=lo)&(finals<=(10**9 if hi is None else hi))).mean()) for b,(lo,hi) in branges}

prc=pd.read_parquet(OUT/'clob_prices.parquet')
price_idx={}
for (sl,bk),g in prc.sort_values('t').groupby(['auction_slug','bucket']): price_idx[(sl,bk)]=(g['t'].to_numpy(),g['price'].to_numpy())
buckets_by=prc.groupby('auction_slug')['bucket'].apply(lambda s:sorted(set(s.dropna()))).to_dict()
def price_at(sl,bk,t):
    a=price_idx.get((sl,bk))
    if a is None: return None
    ts,ps=a; i=np.searchsorted(ts,t,side='right')-1
    if i<0: return None
    v=float(ps[i]); return v if 0<v<1 else None

auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
    except: return None
    y2=yr+(1 if mo2<mo1 else 0)
    return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),None)
        if '-' in l: a,b=l.split('-');return(int(a),int(b))
        return (int(l),int(l))
    except: return None
cand=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(auc.confidence.isin(['high','medium']))&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
sel=[]
for _,a in cand.iterrows():
    w=noon(a['auction_slug'],a['start_utc'].year)
    if not w: continue
    s,e=w; dur=a['duration_type']; days=(e-s)/86400
    if dur=='7-day' and not 6.5<=days<=7.6: continue
    if dur=='2-day' and not 1.5<=days<=2.6: continue
    if e>c1 or s<c0+7200: continue
    branges=[(b,pbk(b)) for b in buckets_by.get(a['auction_slug'],[]) if (a['auction_slug'],b) in price_idx and pbk(b)]
    if not branges or obs(s,e)<=0: continue
    sel.append({'slug':a['auction_slug'],'dur':dur,'s':s,'e':e,'winner':str(a['winning_bucket']),'branges':branges,'actual':obs(s,e)})
sel=sorted(sel,key=lambda x:x['s'])

POINT=['Linear','K_base','K_recent','K_recent_sleep','Accrual']
ALLM=POINT+['PF','Ens_KPF','Ens_All','MARKET']
def kbase_rate(o,eh,rates):
    if not rates: return o/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)

err={m:[] for m in POINT}
hit={(m,c,d):[] for m in ALLM for c in ['T-1d','T-1h'] for d in ['2-day','7-day']}
bri={(m,c,d):[] for m in ALLM for c in ['T-1d','T-1h'] for d in ['2-day','7-day']}
for a in sel:
    s,e,winner,branges=a['s'],a['e'],a['winner'],a['branges']; total=(e-s)/3600; dur=a['dur']; act=a['actual']
    priors=[p['actual']/((p['e']-p['s'])/3600) for p in sel if p['e']<s and p['e']>p['s']]
    prior_rate=float(np.mean(priors)) if priors else 1.7
    mult=diurnal_mult(s)
    for cn,hr in [('T-1d',24),('T-1h',1)]:
        eh=total-hr
        if eh<=0.5: continue
        cps=s+int(eh*3600); o=obs(s,cps)
        mk={b:price_at(a['slug'],b,cps) for b,_ in branges}; mk={b:v for b,v in mk.items() if v is not None}
        if winner not in mk or sum(mk.values())<=0: continue
        sh=share_wf(48 if dur=='2-day' else 168, s)
        er=ewma_rate(s,cps); ed=ewma_deseason(s,cps,mult); effr=eff_remaining(cps,e,mult)
        pts={'Linear':o*total/eh,'K_base':o+kbase_rate(o,eh,priors)*hr,
             'K_recent':o+(er if er is not None else o/max(eh,1))*hr,
             'K_recent_sleep':o+(ed if ed is not None else o/max(eh,1))*effr}
        if sh is not None:
            idx=min(len(sh)-1,max(0,int(eh)-1)); pts['Accrual']=o/sh[idx]
        sig={m:(float(np.std(err[m])) if len(err[m])>=5 else max(8.0,0.15*max(pts.get(m,o),1))) for m in POINT}
        probs={}
        for m in POINT:
            if m not in pts: continue
            wp={b:bprob(pts[m],sig[m],lo,hi) for b,(lo,hi) in branges}; t=sum(wp.values()) or 1; probs[m]={b:v/t for b,v in wp.items()}
        pfp=pf_probs(s,cps,e,prior_rate,mult,branges); t=sum(pfp.values()) or 1; probs['PF']={b:v/t for b,v in pfp.items()}
        def avg(keys):
            ks=[k for k in keys if k in probs]
            if not ks: return None
            v={b:float(np.mean([probs[k][b] for k in ks])) for b,_ in branges}; t=sum(v.values()) or 1; return {b:x/t for b,x in v.items()}
        probs['Ens_KPF']=avg(['K_base','PF'])
        probs['Ens_All']=avg(['K_base','K_recent_sleep','Accrual','PF'])
        t=sum(mk.values()); probs['MARKET']={b:v/t for b,v in mk.items()}
        for m in ALLM:
            P=probs.get(m)
            if not P: continue
            fav=max(P,key=P.get)
            hit[(m,cn,dur)].append(1 if fav==winner else 0)
            bri[(m,cn,dur)].append(sum((P.get(b,0)-(1.0 if b==winner else 0))**2 for b,_ in branges))
    eh=total-24
    if eh>0.5:
        cps=s+int(eh*3600); o=obs(s,cps); er=ewma_rate(s,cps); ed=ewma_deseason(s,cps,mult); effr=eff_remaining(cps,e,mult)
        ref={'Linear':o*total/eh,'K_base':o+kbase_rate(o,eh,priors)*24,
             'K_recent':o+(er if er is not None else o/max(eh,1))*24,'K_recent_sleep':o+(ed if ed is not None else o/max(eh,1))*effr}
        sh=share_wf(48 if dur=='2-day' else 168, s)
        if sh is not None:
            idx=min(len(sh)-1,max(0,int(eh)-1)); ref['Accrual']=o/sh[idx]
        for m in POINT:
            if m in ref: err[m].append(act-ref[m])

def ci(v):
    n=len(v)
    if not n: return (float('nan'),0.0,0)
    p=np.mean(v); return (100*p,100*1.96*math.sqrt(max(p*(1-p),1e-9)/n),n)
print("Q1 K_recent/K_recent_sleep | Q2 Ens_KPF | Q3 Ens_All | MARKET = the bar to beat\n")
for cn in ['T-1d','T-1h']:
    for dur in ['2-day','7-day']:
        n=len(hit[('MARKET',cn,dur)])
        print(f"=== {cn}  {dur}  (n={n}) — bracket-hit % [95% CI]  |  Brier (lower=better) ===")
        for m in ALLM:
            h,hw,nn=ci(hit[(m,cn,dur)]); b=np.mean(bri[(m,cn,dur)]) if bri[(m,cn,dur)] else float('nan')
            star=' <== MARKET (benchmark)' if m=='MARKET' else ''
            print(f"  {m:<16} {h:5.0f}% +/-{hw:3.0f}   brier {b:.3f}{star}")
        print()
