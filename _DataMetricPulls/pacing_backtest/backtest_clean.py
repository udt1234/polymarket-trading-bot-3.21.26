"""Clean rebuild: 10 pacing models on the X-API backfill (correct counts) + noon-ET windows,
current-structure auctions only (7-day Sep5 2025+, 2-day Jan5 2026+). Walk-forward.
Outputs backtest_clean_results.csv (with observed cols) + prints point-error leaderboard.
"""
import sys, math, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')
np.random.seed(42)
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'; OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
ET = ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

# ---- clean tweet source (counting posts only) ----
bf = pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet')
bf = bf[bf.counts_main_feed].sort_values('ms').reset_index(drop=True)
post_ts = (bf.ms.to_numpy()//1000).astype('int64')
m_repost=(bf['type']=='repost').to_numpy(); m_quote=(bf['type']=='quote').to_numpy(); m_reply=(bf['type']=='reply').to_numpy()
cover0 = int(post_ts.min()); cover1 = int(post_ts.max())
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))
def times_in(s,e):
    lo=np.searchsorted(post_ts,s); hi=np.searchsorted(post_ts,e)
    return (post_ts[lo:hi]-s)/3600.0, m_reply[lo:hi], m_repost[lo:hi], m_quote[lo:hi]

# ---- auctions (current structure, noon-ET windows) ----
auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def parse_noonET(slug, ref_year):
    toks=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[toks[0].lower()]; d1=int(toks[1])
        if len(toks)>=4 and toks[2].lower() in MONTHS: mo2=MONTHS[toks[2].lower()]; d2=int(toks[3])
        else: mo2=mo1; d2=int(toks[2])
    except Exception: return None
    y2=ref_year+(1 if mo2<mo1 else 0)
    return (pd.Timestamp(datetime(ref_year,mo1,d1,12,0,tzinfo=ET)).tz_convert('UTC'),
            pd.Timestamp(datetime(y2,mo2,d2,12,0,tzinfo=ET)).tz_convert('UTC'))

cand = auc[(auc.duration_type.isin(['2-day','7-day'])) & (auc.winning_bucket!='')
           & (~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))].copy()
sel=[]
for _,a in cand.iterrows():
    w=parse_noonET(a['auction_slug'], a['start_utc'].year)
    if not w: continue
    ns,ne=w; dur=a['duration_type']
    days=(ne-ns).total_seconds()/86400
    if dur=='7-day' and not (6.5<=days<=7.6): continue
    if dur=='2-day' and not (1.5<=days<=2.6): continue
    if dur=='7-day' and ns < pd.Timestamp('2025-09-05',tz='UTC'): continue
    if dur=='2-day' and ns < pd.Timestamp('2026-01-05',tz='UTC'): continue
    s=int(ns.timestamp()); e=int(ne.timestamp())
    if s < cover0+7200 or e > cover1: continue   # fully covered by backfill
    sel.append({'slug':a['auction_slug'],'dur':dur,'conf':a['confidence'],'winner':a['winning_bucket'],
                's':s,'e':e,'ns':ns,'ne':ne,'actual':obs(s,e)})
sel=[x for x in sel if x['actual']>0]
sel=sorted(sel, key=lambda x:x['s'])
print(f"clean tweet source: {len(bf)} counting posts, {datetime.utcfromtimestamp(cover0)} -> {datetime.utcfromtimestamp(cover1)}")
print(f"current-structure auctions selected: {len(sel)} "
      f"(7d={sum(1 for x in sel if x['dur']=='7-day')}, 2d={sum(1 for x in sel if x['dur']=='2-day')})")

# ---- models (same as canonical harness, fixed Hawkes) ----
def m_linear(o,eh,rh): return 0 if eh<=0 else o*(eh+rh)/eh
def m_curbayes(o,eh,rh,pool):
    th=eh+rh
    if not pool or o<=0 or eh<=0: return float(np.mean(pool)) if pool else 0
    ec=min(0.99,max(0.001,eh/th)); op=o/ec; pm=float(np.mean(pool))
    ps=max(1.0,float(np.std(pool,ddof=1)) if len(pool)>1 else pm*0.25)
    ov=max(1.0,o*(1-ec)/(ec**2)); pp=1/ps**2; po=1/ov
    return (pp*pm+po*op)/(pp+po)
def m_gp(o,eh,rh,pt,pd_):
    if not pt: return o*(eh+rh)/max(eh,1)
    lp=(sum(pt)+o)/(sum(pd_)+eh) if (sum(pd_)+eh)>0 else 0
    return o+lp*rh
def m_seasonal(o,eh,rh,sm,cur,dflt):
    if not sm: return o*(eh+rh)/max(eh,1)
    er=0.0
    for h in range(int(rh)):
        et=pd.Timestamp(cur+h*3600,unit='s',tz='UTC').tz_convert('America/New_York')
        er+=sm.get((et.dayofweek,et.hour),dflt)
    return o+er
def m_decay(o,eh,rh,pwa,eps=0.85):
    if not pwa: return o*(eh+rh)/max(eh,1)
    a0=sum(t*(eps**ag) for t,_,ag in pwa); b0=sum(d*(eps**ag) for _,d,ag in pwa) or 1
    return o+(a0+o)/(b0+eh)*rh
def _nll(p,ev,T):
    mu,al,be=p
    if mu<=0 or al<0 or be<=0 or al>=be: return 1e10
    ll=0.0; ds=0.0; pt=0.0
    for i,t in enumerate(ev):
        ds=ds*math.exp(-be*(t-pt))+1.0 if i>0 else 0.0
        inten=mu+al*ds
        if inten<=0: return 1e10
        ll+=math.log(inten); pt=t
    integ=mu*T+sum((al/be)*(1-math.exp(-be*(T-t))) for t in ev)
    return -(ll-integ)
def fit_hawkes(ev,T):
    if len(ev)<5: return None
    try:
        r=minimize(_nll,[len(ev)/T*0.5,0.5,1.0],args=(ev,T),method='Nelder-Mead',options={'maxiter':200,'xatol':1e-3,'fatol':1e-3})
        if r.success or r.fun<1e9:
            mu,al,be=r.x
            if mu>0 and al>=0 and be>0 and al<be: return (mu,al,be)
    except Exception: pass
    return None
def sim_hawkes(mu,al,be,t0,t1,hist,n=50):
    if mu<=0 or be<=0: return 0
    h=np.asarray(hist,float); A0=float(np.sum(np.exp(-be*(t0-h)))) if len(h) else 0.0
    tot=[]
    for _ in range(n):
        A=A0; t=t0; c=0
        while True:
            lb=mu+al*A
            if lb<=0: break
            w=np.random.exponential(1.0/lb); t+=w
            if t>=t1: break
            A*=math.exp(-be*w)
            if np.random.random()<(mu+al*A)/lb:
                A+=1.0; c+=1
                if c>=5000: break
        tot.append(c)
    return float(np.mean(tot)) if tot else 0
def m_hawkes(o,eh,rh,ev,fit):
    if fit is None: return o*(eh+rh)/max(eh,1)
    return o+sim_hawkes(*fit,eh,eh+rh,ev)
def m_marked(o,eh,rh,ev,marks,fit):
    if not len(ev): return o*(eh+rh)/max(eh,1)
    ir,rp,qt=marks; mw=np.where(rp,1.2,np.where(qt,0.7,1.0))
    if fit is None: return o*(eh+rh)/max(eh,1)
    mu,al,be=fit; alm=al*float(np.mean(mw)) if len(mw) else al
    return o+sim_hawkes(mu,alm,be,eh,eh+rh,ev,n=30)
def bayes_hawkes_samples(ev,T,n_iter=600,burn=250):
    # Metropolis-Hastings posterior over (mu,alpha,beta): Hawkes likelihood + half-normal
    # priors + stability constraint alpha<beta. Returns posterior samples.
    if len(ev)<5: return None
    def logpost(p):
        mu,al,be=p
        if mu<=0 or al<0 or be<=0 or al>=be: return -1e18
        nll=_nll(p,ev,T)
        if nll>=1e9: return -1e18
        return -nll - 0.5*((mu/3.0)**2+(al/2.0)**2+(be/4.0)**2)
    cur=[max(0.05,len(ev)/T*0.5),0.5,1.2]; clp=logpost(cur); step=[0.08,0.08,0.15]; samples=[]
    for it in range(n_iter):
        prop=[cur[i]+np.random.normal(0,step[i]) for i in range(3)]; plp=logpost(prop)
        if math.log(np.random.random()+1e-12) < plp-clp: cur=prop; clp=plp
        if it>=burn and it%4==0: samples.append(tuple(cur))
    return samples or None
def m_bayes_hawkes(o,eh,rh,ev):
    s=bayes_hawkes_samples(ev,eh)
    if not s: return o*(eh+rh)/max(eh,1)
    counts=[sim_hawkes(mu,al,be,eh,eh+rh,ev,n=6) for (mu,al,be) in s[:25]]   # posterior-predictive
    return o+float(np.mean(counts))
def m_mmpp(o,eh,rh,rates):
    if not rates: return o*(eh+rh)/max(eh,1)
    return o+(0.5*(o/max(eh,1))+0.5*float(np.mean(rates)))*rh
def m_negbin(o,eh,rh,pt):
    if not pt: return o*(eh+rh)/max(eh,1)
    me=float(np.mean(pt))
    if len(pt)<2: return me
    pf=(o/max(eh,1))/(me/(eh+rh)) if me>0 else 1
    return me*(0.7+0.3*pf)
def m_kalman(o,eh,rh,rates):
    if not rates: return o*(eh+rh)/max(eh,1)
    x=float(np.mean(rates)); P=float(np.var(rates))+0.01; R=max(0.1,P*0.5)
    K=(P+0.01)/(P+0.01+R); xn=x+K*(o/max(eh,1)-x)
    return o+xn*rh

MODELS=['Linear','CurBayes','M0','M1Seas','Decay','M2Hawk','M3Hawk','M6BHawk','M4MMPP','M5NB','Kalman']
results=[]
t0=time.time()
for idx,a in enumerate(sel):
    if idx%20==0: print(f"  {idx}/{len(sel)} ({time.time()-t0:.0f}s)")
    s,e,actual=a['s'],a['e'],a['actual']; total_h=(e-s)/3600
    priors=[p for p in sel if p['e']<s]
    pt=[p['actual'] for p in priors]; pdur=[(p['e']-p['s'])/3600 for p in priors]
    prate=[p['actual']/((p['e']-p['s'])/3600) for p in priors if p['e']>p['s']]
    pwa=[(p['actual'],(p['e']-p['s'])/3600,(s-p['e'])/604800) for p in priors]
    # seasonal map from clean history before s
    sm={}; dflt=float(np.mean(prate)) if prate else 1.0
    hi=np.searchsorted(post_ts,s)
    if hi>100:
        hd=pd.to_datetime(post_ts[:hi],unit='s',utc=True).tz_convert('America/New_York')
        cnts=pd.DataFrame({'dow':hd.dayofweek,'hour':hd.hour}).groupby(['dow','hour']).size()
        span=max(1,(s-post_ts[0])/86400); occ=span/7
        for (dw,hr),cc in cnts.items(): sm[(dw,hr)]=cc/occ
    row={'slug':a['slug'],'dur':a['dur'],'conf':a['conf'],'ns':a['ns'].strftime('%Y-%m-%d %H:%M'),
         'ne':a['ne'].strftime('%Y-%m-%d %H:%M'),'total_hours':round(total_h,1),'actual':actual,'winner':a['winner']}
    for hr in [48,24]:
        eh=total_h-hr; suf=f'_T{hr//24}d'
        if eh<=0.5:
            for mm in MODELS: row[f'{mm}{suf}']=''; row[f'{mm}{suf}_err%']=''
            row[f'obs{suf}']=''
            continue
        cps=s+int(eh*3600); o=obs(s,cps); row[f'obs{suf}']=o
        ev,ir,rp,qt=times_in(s,cps); ev=ev.tolist()
        fit=fit_hawkes(ev,eh) if len(ev)>=5 else None
        preds={'Linear':m_linear(o,eh,hr),'CurBayes':m_curbayes(o,eh,hr,pt),'M0':m_gp(o,eh,hr,pt,pdur),
               'M1Seas':m_seasonal(o,eh,hr,sm,cps,dflt),'Decay':m_decay(o,eh,hr,pwa),
               'M2Hawk':m_hawkes(o,eh,hr,ev,fit),'M3Hawk':m_marked(o,eh,hr,ev,(ir,rp,qt),fit),
               'M6BHawk':m_bayes_hawkes(o,eh,hr,ev),
               'M4MMPP':m_mmpp(o,eh,hr,prate),'M5NB':m_negbin(o,eh,hr,pt),'Kalman':m_kalman(o,eh,hr,prate)}
        for nm,pv in preds.items():
            row[f'{nm}{suf}']=round(pv,0)
            row[f'{nm}{suf}_err%']=round(abs(pv-actual)/actual*100,1) if actual>0 else ''
    results.append(row)
df=pd.DataFrame(results); df.to_csv(OUT/'backtest_clean_results.csv',index=False)
print(f"\nCompleted {len(df)} auctions in {time.time()-t0:.0f}s -> backtest_clean_results.csv")

print("\n=== POINT-ERROR leaderboard (mean abs err %) ===")
print(f"{'Model':<10}{'T-2d':>9}{'T-1d':>9}{'n2':>5}{'n1':>5}")
tab=[]
for m in MODELS:
    t2=pd.to_numeric(df.get(f'{m}_T2d_err%'),errors='coerce').dropna()
    t1=pd.to_numeric(df.get(f'{m}_T1d_err%'),errors='coerce').dropna()
    tab.append((m,t2.mean() if len(t2) else 999,t1.mean() if len(t1) else 999,len(t2),len(t1)))
for m,a2,a1,n2,n1 in sorted(tab,key=lambda x:x[2]):
    print(f"{m:<10}{a2:>8.1f}%{a1:>8.1f}%{n2:>5}{n1:>5}")
