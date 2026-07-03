"""Bracket hit-rate at T-2d / T-1d / T-1h for the 10 models + 3 NEW sleep-aware models
(Linear_S, Kalman_S, M4MMPP_S = rate x effective-hours, shaping the remaining window by his
hour-of-day profile so sleep hours add ~0). Hit = forecast lands inside the winning bracket."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8'); np.random.seed(42)
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON=ROOT/'_DataMetricPulls'/'canonical'; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms').reset_index(drop=True)
post_ts=(bf.ms.to_numpy()//1000).astype('int64'); cover0,cover1=int(post_ts.min()),int(post_ts.max())
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))
auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
    except Exception: return None
    y2=yr+(1 if mo2<mo1 else 0)
    return (pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).tz_convert('UTC'),pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).tz_convert('UTC'))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-');return(int(a),int(b))
        return (int(l),int(l))
    except Exception: return None
cand=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))].copy()
sel=[]
for _,a in cand.iterrows():
    w=noon(a['auction_slug'],a['start_utc'].year)
    if not w: continue
    ns,ne=w; days=(ne-ns).total_seconds()/86400; dur=a['duration_type']
    if dur=='7-day' and not 6.5<=days<=7.6: continue
    if dur=='2-day' and not 1.5<=days<=2.6: continue
    s=int(ns.timestamp()); e=int(ne.timestamp())
    if e>cover1 or s<cover0+7200: continue
    wb=pbk(a['winning_bucket'])
    if wb and obs(s,e)>0: sel.append({'slug':a['auction_slug'],'dur':dur,'s':s,'e':e,'actual':obs(s,e),'wb':wb})
sel=sorted(sel,key=lambda x:x['s'])
def m_linear(o,eh,rh): return 0 if eh<=0 else o*(eh+rh)/eh
def m_curbayes(o,eh,rh,pool):
    th=eh+rh
    if not pool or o<=0 or eh<=0: return float(np.mean(pool)) if pool else 0
    ec=min(0.99,max(0.001,eh/th));op=o/ec;pm=float(np.mean(pool));ps=max(1.0,float(np.std(pool,ddof=1)) if len(pool)>1 else pm*0.25)
    ov=max(1.0,o*(1-ec)/(ec**2));pp=1/ps**2;po=1/ov;return (pp*pm+po*op)/(pp+po)
def m_gp(o,eh,rh,pt,pd_): return (o+((sum(pt)+o)/(sum(pd_)+eh) if sum(pd_)+eh>0 else 0)*rh) if pt else o*(eh+rh)/max(eh,1)
def m_decay(o,eh,rh,pwa,eps=0.85):
    if not pwa: return o*(eh+rh)/max(eh,1)
    a0=sum(t*eps**ag for t,_,ag in pwa);b0=sum(d*eps**ag for _,d,ag in pwa) or 1;return o+(a0+o)/(b0+eh)*rh
def m_mmpp(o,eh,rh,rates): return o+(0.5*(o/max(eh,1))+0.5*float(np.mean(rates)))*rh if rates else o*(eh+rh)/max(eh,1)
def m_negbin(o,eh,rh,pt):
    if not pt: return o*(eh+rh)/max(eh,1)
    me=float(np.mean(pt))
    if len(pt)<2: return me
    pf=(o/max(eh,1))/(me/(eh+rh)) if me>0 else 1;return me*(0.7+0.3*pf)
def m_kalman_rate(o,eh,rates):
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)
def m_seasonal(o,eh,rh,sm,cur,dflt):
    if not sm: return o*(eh+rh)/max(eh,1)
    return o+sum(sm.get((pd.Timestamp(cur+h*3600,unit='s',tz='UTC').tz_convert(ET).dayofweek,pd.Timestamp(cur+h*3600,unit='s',tz='UTC').tz_convert(ET).hour),dflt) for h in range(int(rh)))
def eff_hours(sm,cps,rh,mean_sm,dflt):
    if not sm or mean_sm<=0: return rh
    return sum((sm.get((pd.Timestamp(cps+h*3600,unit='s',tz='UTC').tz_convert(ET).dayofweek,pd.Timestamp(cps+h*3600,unit='s',tz='UTC').tz_convert(ET).hour),dflt))/mean_sm for h in range(int(rh)))
MODELS=['Linear','Kalman','M4MMPP','CurBayes','M0','M1Seas','Decay','M5NB','Linear_S','Kalman_S','M4MMPP_S']
ckpts=[('T-2d',48),('T-1d',24),('T-1h',1)]
hits={(m,c[0],d):[] for m in MODELS for c in ckpts for d in ['2-day','7-day']}
for a in sel:
    s,e=a['s'],a['e'];total_h=(e-s)/3600;dur=a['dur'];lo,hi=a['wb']
    priors=[p for p in sel if p['e']<s]
    pt=[p['actual'] for p in priors];pdur=[(p['e']-p['s'])/3600 for p in priors]
    prate=[p['actual']/((p['e']-p['s'])/3600) for p in priors if p['e']>p['s']]
    pwa=[(p['actual'],(p['e']-p['s'])/3600,(s-p['e'])/604800) for p in priors]
    sm={};dflt=float(np.mean(prate)) if prate else 1.0;hidx=np.searchsorted(post_ts,s)
    if hidx>100:
        hd=pd.to_datetime(post_ts[:hidx],unit='s',utc=True).tz_convert(ET)
        cnts=pd.DataFrame({'dow':hd.dayofweek,'hour':hd.hour}).groupby(['dow','hour']).size()
        occ=max(1,(s-post_ts[0])/86400)/7
        for (dw,hr),cc in cnts.items(): sm[(dw,hr)]=cc/occ
    mean_sm=float(np.mean(list(sm.values()))) if sm else dflt
    for cname,hr in ckpts:
        eh=total_h-hr
        if eh<=0.5: continue
        cps=s+int(eh*3600);o=obs(s,cps);cur=o/eh
        ef=eff_hours(sm,cps,hr,mean_sm,dflt)
        krate=m_kalman_rate(o,eh,prate) if prate else cur
        preds={'Linear':m_linear(o,eh,hr),'Kalman':o+krate*hr,'M4MMPP':m_mmpp(o,eh,hr,prate),
               'CurBayes':m_curbayes(o,eh,hr,pt),'M0':m_gp(o,eh,hr,pt,pdur),'M1Seas':m_seasonal(o,eh,hr,sm,cps,dflt),
               'Decay':m_decay(o,eh,hr,pwa),'M5NB':m_negbin(o,eh,hr,pt),
               'Linear_S':o+cur*ef,'Kalman_S':o+krate*ef,'M4MMPP_S':o+(0.5*cur+0.5*(float(np.mean(prate)) if prate else cur))*ef}
        for m,pv in preds.items():
            hits[(m,cname,dur)].append(1 if lo<=round(pv)<=hi else 0)
n2=sum(1 for a in sel if a['dur']=='2-day');n7=sum(1 for a in sel if a['dur']=='7-day')
print(f"auctions: {n2} two-day, {n7} seven-day\n")
for dur in ['2-day','7-day']:
    print(f"=== {dur.upper()} — % landed in WINNING bracket ===")
    print(f"{'Model':<11}"+"".join(f"{c[0]:>8}" for c in ckpts))
    for m in MODELS:
        cellvals=[]
        for c in ckpts:
            h=hits[(m,c[0],dur)];cellvals.append(100*np.mean(h) if h else None)
        print(f"{m:<11}"+"".join((f"{x:>7.0f}%" if x is not None else f"{'n/a':>8}") for x in cellvals))
    print()
