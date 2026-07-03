"""Particle Filter for Elon's posting rate (per the Polybot_Estimator_Methods doc), with the
diurnal hour-of-day shape layered in (the 'accrual on top' idea). State = latent baseline rate
lambda; instantaneous rate = lambda * diurnal_mult(ET hour). Poisson likelihood (no Gaussian
hack). Posterior particle cloud -> forecast distribution of the final count -> bracket prob.
Backtested vs Kalman + AccrualCurve at T-1d / T-1h on the canonical auctions, walk-forward."""
import sys, json, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8'); rng=np.random.default_rng(7)
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON=ROOT/'_DataMetricPulls'/'canonical'; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms').reset_index(drop=True)
pt=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pt.min()),int(pt.max())
def obs(s,e): return int(np.searchsorted(pt,e)-np.searchsorted(pt,s))
# diurnal multiplier (mean 1) over ET hour-of-day, WALK-FORWARD: built per-auction from posts
# BEFORE the auction starts, so it never peeks at the future hour-of-day mix.
hd_all=pd.to_datetime(pt,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
_multcache={}
def diurnal_mult(before_s):
    if before_s in _multcache: return _multcache[before_s]
    h=hd_all[pt<before_s]
    if len(h)<240: r=np.ones(24)                          # <~10 days history -> flat (no diurnal info yet)
    else:
        m=np.array([np.sum(h==hh) for hh in range(24)],float); r=m/m.mean() if m.mean()>0 else np.ones(24)
    _multcache[before_s]=r; return r
_sharecache={}
def build_share_wf(dur_h, before_ts):                     # walk-forward accrual share (windows closed before before_ts)
    k=(dur_h,before_ts)
    if k in _sharecache: return _sharecache[k]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None
    _sharecache[k]=r; return r
def hour_counts(s,e):
    n=int((e-s)/3600); cnt=np.array([obs(s+h*3600,s+(h+1)*3600) for h in range(n)])
    hrs=np.array([pd.Timestamp(s+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(n)])
    return cnt,hrs

M=500
def pf_forecast(s,cps,e,prior_rate,mult):
    obs_cnt,obs_hr=hour_counts(s,cps)
    lam=rng.lognormal(math.log(max(prior_rate,0.2)),0.6,M)   # prior particles (baseline posts/hr)
    for n,H in zip(obs_cnt,obs_hr):
        lam*=np.exp(rng.normal(0,0.12,M))                    # drift
        mu=np.maximum(lam*mult[H],1e-4)
        logw=n*np.log(mu)-mu                                 # Poisson log-likelihood
        w=np.exp(logw-logw.max()); w/=w.sum()
        idx=rng.choice(M,M,p=w); lam=lam[idx]*np.exp(rng.normal(0,0.03,M))  # resample + jitter
    rem_hr=[pd.Timestamp(cps+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(int((e-cps)/3600))]
    rm=np.array([mult[H] for H in rem_hr]).sum() if rem_hr else 0.0
    o=obs(s,cps)
    finals=o+rng.poisson(np.clip(lam*rm,0,1e4))              # one sample per particle
    return float(np.mean(finals)), finals

# auctions
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
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-');return(int(a),int(b))
        return (int(l),int(l))
    except: return None
cand=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
sel=[]
for _,a in cand.iterrows():
    w=noon(a['auction_slug'],a['start_utc'].year)
    if not w: continue
    s,e=w; dur=a['duration_type']; days=(e-s)/86400
    if dur=='7-day' and not 6.5<=days<=7.6: continue
    if dur=='2-day' and not 1.5<=days<=2.6: continue
    if e>c1 or s<c0+7200: continue
    wb=pbk(a['winning_bucket'])
    if wb and obs(s,e)>0: sel.append({'dur':dur,'s':s,'e':e,'actual':obs(s,e),'wb':wb})
sel=sorted(sel,key=lambda x:x['s'])
def krate(o,eh,rates):
    if not rates: return o/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)

for hr,lab in [(24,'T-1d'),(1,'T-1h')]:
    R={m:{'2-day':[],'7-day':[]} for m in ['ParticleFilter','Kalman','Accrual']}
    E={m:{'2-day':[],'7-day':[]} for m in ['ParticleFilter','Kalman','Accrual']}
    PB={'2-day':[],'7-day':[]}
    for a in sel:
        s,e=a['s'],a['e']; total=(e-s)/3600; eh=total-hr
        if eh<=0.5: continue
        cps=s+int(eh*3600); o=obs(s,cps); lo,hi=a['wb']; act=a['actual']
        priors=[p['actual']/((p['e']-p['s'])/3600) for p in sel if p['e']<s and p['e']>p['s']]
        prior_rate=float(np.mean(priors)) if priors else 1.7
        mult=diurnal_mult(s)                                 # walk-forward diurnal shape (built from posts before s)
        pf,finals=pf_forecast(s,cps,e,prior_rate,mult)
        proj={'ParticleFilter':pf,'Kalman':o+krate(o,eh,priors)*hr}
        sh=build_share_wf(48 if a['dur']=='2-day' else 168, s)  # walk-forward accrual baseline
        if sh is not None:
            idx=min(len(sh)-1,max(0,int(eh)-1)); proj['Accrual']=o/sh[idx]
        for m,pv in proj.items():
            R[m][a['dur']].append(1 if lo<=round(pv)<=hi else 0)
            E[m][a['dur']].append(abs(pv-act)/act*100)
        PB[a['dur']].append(1 if lo<=round(np.median(finals)) and np.mean((finals>=lo)&(finals<=hi))==max(np.mean((finals>=lo)&(finals<=hi)),0) else 0)
    print(f"\n=== {lab} : bracket-hit % (mean err%) ===")
    print(f"{'model':<15}{'2d hit':>8}{'2d err':>8}{'7d hit':>8}{'7d err':>8}")
    for m in ['ParticleFilter','Kalman','Accrual']:
        def hh(d): v=R[m][d]; return 100*np.mean(v) if v else float('nan')
        def ee(d): v=E[m][d]; return np.mean(v) if v else float('nan')
        print(f"{m:<15}{hh('2-day'):>7.0f}%{ee('2-day'):>7.0f}%{hh('7-day'):>7.0f}%{ee('7-day'):>7.0f}%")
