# -*- coding: utf-8 -*-
"""PACING LEADERBOARD v3 -- Hawkes validation. Same walk-forward harness/auction-set as pacing_leaderboard.py,
but adds the models that were NEVER in the original bake-off: AccrualCurve (raw), Hawkes, Particle Filter,
Finish Line -- head-to-head vs the LOCKED Ens+CAP1.5. Two lenses: (1) bracket-HIT% at 5 checkpoints,
(2) OVERSHOOT (median |err|%, MEAN signed bias%, worst over-projection). Ranks so we can see if Hawkes
actually beats the locked model on BOTH accuracy and overshoot before recommending a switch."""
import sys, glob, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); rng=np.random.default_rng(7)
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
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
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
_sc={}
def share_wf(dur_h,before_ts):
    if (dur_h,before_ts) in _sc: return _sc[(dur_h,before_ts)]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None; _sc[(dur_h,before_ts)]=r; return r
_dm={}
def diurnal(before_s):
    if before_s in _dm: return _dm[before_s]
    h=hd_all[pts<before_s]; r=np.ones(24) if len(h)<240 else (lambda m:m/m.mean())(np.array([np.sum(h==hh) for hh in range(24)],float)); _dm[before_s]=r; return r
# --- new models ---
def hawkes_pace(s,cps,rh,o):
    hc=[obs(s+h*3600,s+(h+1)*3600) for h in range(int((cps-s)/3600))]; rem=int(round(rh))
    if not hc or rem<=0: return float(o)
    c=hc; mr=sum(c)/len(c) if c else 0.5
    if len(c)<6: mu,al,be=0.5,0.8,1.2
    else:
        bp=sum(1 for i in range(1,len(c)) if c[i]>0 and c[i-1]>0); clus=bp/max(len(c)-1,1)
        thr=mr*1.5; ch=mx=0
        for x in c:
            if x>thr: ch+=1; mx=max(mx,ch)
            else: ch=0
        mu,al,be=max(mr*0.3,0.1),min(clus*1.5,0.95),max(min(1.0/max(mx,1),3.0),0.3)
    evt=[]; t=0.0
    for cnt in hc:
        for _ in range(int(cnt)): evt.append(t+0.5)
        t+=1.0
    proj=float(o)
    for ha in range(rem):
        ct=t+ha; it=mu+sum(al*math.exp(-be*(ct-x)) for x in evt if x<ct); proj+=max(it,0)
        if it>0.1: evt.append(ct+0.5)
    return proj
def pf_pace(s,cps,e,prior_rate,mult):
    M=300; n=int((cps-s)/3600)
    oc=np.array([obs(s+h*3600,s+(h+1)*3600) for h in range(n)]) if n>0 else np.array([])
    oh=np.array([pd.Timestamp(s+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(n)]) if n>0 else np.array([],int)
    lam=rng.lognormal(math.log(max(prior_rate,0.2)),0.6,M)
    for cnt,H in zip(oc,oh):
        lam*=np.exp(rng.normal(0,0.12,M)); mu=np.maximum(lam*mult[H],1e-4); logw=cnt*np.log(mu)-mu
        w=np.exp(logw-logw.max()); w/=w.sum(); idx=rng.choice(M,M,p=w); lam=lam[idx]*np.exp(rng.normal(0,0.03,M))
    rem=[pd.Timestamp(cps+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(int((e-cps)/3600))]
    rm=np.array([mult[H] for H in rem]).sum() if rem else 0.0; o=obs(s,cps)
    return float(np.mean(o+rng.poisson(np.clip(lam*rm,0,1e4))))
def finish_line(s,cps,rh,o): return o+(obs(max(s,cps-6*3600),cps)/6.0)*rh

auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
A=[]
for _,a in auc.iterrows():
    if a.duration_type not in ('2-day','7-day') or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w; days=(e-s)/86400
    if a.duration_type=='2-day' and not 1.5<=days<=2.6: continue
    if a.duration_type=='7-day' and not 6.5<=days<=7.6: continue
    if e>c1 or s<c0+7200: continue
    win=pbk(str(a.winning_bucket))
    if not win: continue
    A.append({'slug':a.auction_slug,'s':s,'e':e,'dur':a.duration_type,'win':win,'final':obs(s,e)})
A=sorted(A,key=lambda x:x['s'])
print(f"leaderboard set: {len(A)} auctions ({sum(x['dur']=='2-day' for x in A)}x2d, {sum(x['dur']=='7-day' for x in A)}x7d)",flush=True)
MODELS=['Ens+CAP1.5 (LOCKED)','Kalman','Kalman+Sleep','Ensemble','AccrualCurve','Hawkes','ParticleFilter','FinishLine']
def proj_all(o,eh,rh,total,rmean,ermean,Kk,share,eff_el,eff_rem,cp,s,cps,e,mult):
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    ksl=o+(ermean+Kk*(o/max(eff_el,.1)-ermean))*eff_rem
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))] if share is not None else o*total/eh
    ens=(1-cp)*kal+cp*acc
    cap15=o+min((ens-o)/max(rh,.1),1.5*rmean)*rh
    return {'Ens+CAP1.5 (LOCKED)':cap15,'Kalman':kal,'Kalman+Sleep':ksl,'Ensemble':ens,'AccrualCurve':acc,
            'Hawkes':hawkes_pace(s,cps,rh,o),'ParticleFilter':pf_pace(s,cps,e,rmean,mult),'FinishLine':finish_line(s,cps,rh,o)}
CPS=[0.20,0.35,0.50,0.70,0.90]
res={m:{'hit':[],'err':[],'hit_e':[],'signed':[]} for m in MODELS}; stab={m:[] for m in MODELS}
done=0
for a in A:
    s,e=a['s'],a['e']; total=(e-s)/3600; dur_h=48 if a['dur']=='2-day' else 168; act=a['final']
    if act<=0: continue
    pr=[p['final']/((p['e']-p['s'])/3600) for p in A if p['e']<s and p['dur']==a['dur']]
    pf_=[p['final'] for p in A if p['e']<s and p['dur']==a['dur']]
    if len(pf_)<4: continue
    mult=diurnal(s); share=share_wf(dur_h,s)
    rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
    hours=pd.to_datetime(s+np.arange(dur_h+1)*3600,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
    effcum=np.concatenate([[0],np.cumsum(mult[hours[:-1]])])
    per=[p['final']/max(effcum[-1],0.1) for p in A if p['e']<s and p['dur']==a['dur']]; ermean=float(np.mean(per)) if per else rmean
    lo,hi=a['win']
    for cp in CPS:
        cps=s+int(cp*(e-s)); eh=(cps-s)/3600; rh=total-eh; o=obs(s,cps)
        if eh<1 or rh<0.3: continue
        eff_el=effcum[min(dur_h,int(eh))]; eff_rem=effcum[-1]-eff_el
        pj=proj_all(o,eh,rh,total,rmean,ermean,Kk,share,eff_el,eff_rem,cp,s,cps,e,mult)
        for m,pv in pj.items():
            res[m]['hit'].append(1 if lo<=round(pv)<=hi else 0); res[m]['err'].append(abs(pv-act)/act); res[m]['signed'].append((pv-act)/act)
            if cp<=0.5: res[m]['hit_e'].append(1 if lo<=round(pv)<=hi else 0)
    mx={m:0.0 for m in MODELS}
    for hh in range(4,dur_h,4):
        cps=s+hh*3600; eh=hh; rh=total-eh
        if rh<0.3: continue
        o=obs(s,cps); eff_el=effcum[min(dur_h,hh)]; eff_rem=effcum[-1]-eff_el
        pj=proj_all(o,eh,rh,total,rmean,ermean,Kk,share,eff_el,eff_rem,eh/total,s,cps,e,mult)
        for m,pv in pj.items(): mx[m]=max(mx[m],pv/act)
    for m in MODELS: stab[m].append(mx[m])
    done+=1
    if done%20==0: print(f"  scored {done}/{len(A)}",flush=True)
def agg(v): return (100*np.mean(v)) if v else float('nan')
rows=[]
for m in MODELS:
    r=res[m]
    rows.append({'model':m,'HIT%':agg(r['hit']),'earlyHIT%':agg(r['hit_e']),
        'MEDerr%':100*np.median(r['err']) if r['err'] else np.nan,
        'BIAS%(signed)':100*np.mean(r['signed']) if r['signed'] else np.nan,
        'worst_overproj(x)':float(np.mean(stab[m])) if stab[m] else np.nan,
        'blowup>1.5x%':100*np.mean([1 if v>1.5 else 0 for v in stab[m]]) if stab[m] else np.nan})
lb=pd.DataFrame(rows).sort_values('HIT%',ascending=False)
pd.set_option('display.width',220)
print("\n=== PACING LEADERBOARD v3 (Hawkes validation, walk-forward, all auctions) ===")
print(lb.round(2).to_string(index=False))
lb.to_csv(f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3/leaderboard_hawkes.csv",index=False)
best_hit=lb.iloc[0]['model']; locked=lb[lb.model.str.contains('LOCKED')].iloc[0]
print(f"\nBest bracket-HIT: {best_hit} ({lb.iloc[0]['HIT%']:.1f}%) vs LOCKED Ens+CAP1.5 ({locked['HIT%']:.1f}%)")
print(f"LOCKED overshoot bias {locked['BIAS%(signed)']:+.1f}% | Hawkes bias {lb[lb.model=='Hawkes'].iloc[0]['BIAS%(signed)']:+.1f}%")
