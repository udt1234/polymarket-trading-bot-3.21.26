# -*- coding: utf-8 -*-
"""PACING LEADERBOARD v2. Battery of models, walk-forward, on every resolved auction.
Two scores: (1) ACCURACY at 5 checkpoints (bracket-HIT %, median count ERROR %);
(2) STABILITY = worst over-projection (max proj/actual) swept every 2h across the auction, which
is where the '172' spikes live. Adds RATE-CAPPED variants (a burst cannot project > CAP x the
historical baseline rate) to kill the spikes. Ranks by accuracy AND stability. Picks the top 3."""
import sys, glob, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
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
print(f"leaderboard set: {len(A)} auctions ({sum(x['dur']=='2-day' for x in A)}x2d, {sum(x['dur']=='7-day' for x in A)}x7d)")
MODELS=['Kalman(cur)','Kalman+Sleep','Ensemble','KalmanSleep+CAP2',
        'Ens+CAP1.5','Ens+CAP2','Ens+CAP2.5','Ens+CAPtv','KalmanSleep+CAPtv']
def project(name,o,eh,rh,total,rmean,ermean,Kk,share,eff_el,eff_rem,cp):
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    ksl=o+(ermean+Kk*(o/max(eff_el,.1)-ermean))*eff_rem
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))] if share is not None else o*total/eh
    ens=(1-cp)*kal+cp*acc
    def cap(p,mult):
        r=(p-o)/max(rh,.1); return o+min(r,mult*rmean)*rh         # burst rate capped at mult x baseline
    tv=1.3+1.5*cp                                                  # time-varying: tight early, loose late
    return {'Kalman(cur)':kal,'Kalman+Sleep':ksl,'Ensemble':ens,'KalmanSleep+CAP2':cap(ksl,2.0),
            'Ens+CAP1.5':cap(ens,1.5),'Ens+CAP2':cap(ens,2.0),'Ens+CAP2.5':cap(ens,2.5),
            'Ens+CAPtv':cap(ens,tv),'KalmanSleep+CAPtv':cap(ksl,tv)}

CPS=[0.20,0.35,0.50,0.70,0.90]
res={m:{'hit':[],'err':[],'hit_e':[]} for m in MODELS}; stab={m:[] for m in MODELS}
for a in A:
    s,e=a['s'],a['e']; total=(e-s)/3600; dur_h=48 if a['dur']=='2-day' else 168; act=a['final']
    pr=[p['final']/((p['e']-p['s'])/3600) for p in A if p['e']<s and p['dur']==a['dur']]
    pf=[p['final'] for p in A if p['e']<s and p['dur']==a['dur']]
    mult=diurnal(s); share=share_wf(dur_h,s)
    if len(pf)<4: continue
    rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
    # precompute cumulative effective hours for the whole window (fast eff)
    hours=pd.to_datetime(s+np.arange(dur_h+1)*3600,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
    effcum=np.concatenate([[0],np.cumsum(mult[hours[:-1]])])
    per=[p['final']/max(effcum[-1] if p['dur']==a['dur'] else effcum[-1],0.1) for p in A if p['e']<s and p['dur']==a['dur']]
    ermean=float(np.mean(per)) if per else rmean
    # accuracy at checkpoints
    for cp in CPS:
        cps=s+int(cp*(e-s)); eh=(cps-s)/3600; rh=total-eh; o=obs(s,cps)
        if eh<1 or rh<0.3: continue
        eff_el=effcum[min(dur_h,int(eh))]; eff_rem=effcum[-1]-eff_el
        pj=project(None,o,eh,rh,total,rmean,ermean,Kk,share,eff_el,eff_rem,cp)
        lo,hi=a['win']
        for m,pv in pj.items():
            res[m]['hit'].append(1 if lo<=round(pv)<=hi else 0); res[m]['err'].append(abs(pv-act)/act)
            if cp<=0.5: res[m]['hit_e'].append(1 if lo<=round(pv)<=hi else 0)
    # stability sweep every 2h -> worst over-projection ratio per auction
    mx={m:0.0 for m in MODELS}
    for hh in range(2,dur_h,2):
        cps=s+hh*3600; eh=hh; rh=total-eh
        if rh<0.3: continue
        o=obs(s,cps); eff_el=effcum[min(dur_h,hh)]; eff_rem=effcum[-1]-eff_el
        pj=project(None,o,eh,rh,total,rmean,ermean,Kk,share,eff_el,eff_rem,eh/total)
        for m,pv in pj.items(): mx[m]=max(mx[m],pv/act)
    for m in MODELS: stab[m].append(mx[m])

def agg(v): return (100*np.mean(v)) if v else float('nan')
rows=[]
for m in MODELS:
    r=res[m]
    rows.append({'model':m,'HIT%':agg(r['hit']),'earlyHIT%':agg(r['hit_e']),'MEDerr%':100*np.median(r['err']) if r['err'] else np.nan,
        'worst_overproj(x)':float(np.mean(stab[m])) if stab[m] else np.nan,
        'blowup>1.5x_rate%':100*np.mean([1 if v>1.5 else 0 for v in stab[m]]) if stab[m] else np.nan})
lb=pd.DataFrame(rows)
# composite: reward hit + early hit, punish error + how far the worst over-projection goes
lb['score']=lb['HIT%']+0.3*lb['earlyHIT%']-0.25*lb['MEDerr%']-8*(lb['worst_overproj(x)']-1).clip(lower=0)
lb=lb.sort_values('score',ascending=False)
pd.set_option('display.width',200)
print("\n=== PACING LEADERBOARD v2 (walk-forward) ===")
print(lb.round(2).to_string(index=False))
print("\nTOP 3 (accuracy + stability):", list(lb.model.head(3)))
lb.to_csv(f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3/leaderboard.csv",index=False)
