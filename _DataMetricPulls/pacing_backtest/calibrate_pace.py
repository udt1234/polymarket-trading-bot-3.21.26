# -*- coding: utf-8 -*-
"""CALIBRATE the pace model to the sheet spec (Elon Pacing tab):
  projection = TIME-WEIGHTED ensemble of Kalman (trusted early) and AccrualCurve (trusted late).
  band       = EMPIRICAL overdispersed spread of (final/projection), wide early, tight late
               (walk-forward from prior auctions), NOT the tight sqrt() Normal.
Then check calibration: bin the model's predicted bracket-probability and compare to the ACTUAL
win rate in each bin. A calibrated model sits on the diagonal (predicted == actual).
Compares NEW (ensemble + empirical band) vs OLD (naive Kalman + tight Normal). Counts+winners only,
NO prices/L2 needed, so it runs on EVERY resolved auction. Walk-forward throughout."""
import sys, glob, json, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pts.min()),int(pts.max())
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(lo,hi,mu,sig):
    if sig<=0: sig=1.0
    zl=(lo-0.5-mu)/sig; return max(1e-9,(1-ncdf(zl)) if hi>=10**8 else (ncdf((hi+0.5-mu)/sig)-ncdf(zl)))
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
    k=(dur_h,before_ts)
    if k in _sc: return _sc[k]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None; _sc[k]=r; return r
def kalman_rate(o,eh,rates):
    if not rates: return o/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)

# ---- auctions: every resolved 2-day/7-day with a winner + bracket set ----
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
    try: brks=[pbk(l) for l in json.loads(a.bracket_yes_token_ids).keys() if pbk(l)]
    except: continue
    win=pbk(str(a.winning_bucket))
    if len(brks)<3 or not win: continue
    A.append({'slug':a.auction_slug,'s':s,'e':e,'dur':a.duration_type,'brks':sorted(set(brks)),'win':win,'final':obs(s,e)})
A=sorted(A,key=lambda x:x['s'])
print(f"calibration set: {len(A)} resolved auctions ({sum(x['dur']=='2-day' for x in A)}x2d, {sum(x['dur']=='7-day' for x in A)}x7d)")

CPS=[0.30,0.50,0.70,0.85,0.95]   # elapsed-fraction checkpoints
ratio_hist={cp:[] for cp in CPS}  # walk-forward: prior (final/ensemble_proj) ratios per checkpoint
NEW=[]; OLD=[]                     # (predicted_prob, won)
for a in A:
    s,e=a['s'],a['e']; total=(e-s)/3600; dur_h=48 if a['dur']=='2-day' else 168
    priors=[p['final']/((p['e']-p['s'])/3600) for p in A if p['e']<s and p['e']>p['s']]
    share=share_wf(dur_h,s)
    for cp in CPS:
        cps=s+int(cp*(e-s)); eh=(cps-s)/3600; rh=total-eh; o=obs(s,cps)
        if eh<1 or rh<0.3: continue
        proj_k=o+kalman_rate(o,eh,priors)*rh
        proj=proj_k
        if share is not None:
            idx=min(len(share)-1,max(0,int(eh)-1)); proj_a=o/share[idx]
            proj=(1-cp)*proj_k+cp*proj_a               # time-weighted: Kalman early, Accrual late
        # empirical band from PRIOR ratios at this checkpoint (walk-forward)
        rr=ratio_hist[cp]
        rel=float(np.std(rr)) if len(rr)>=6 else (0.80*(1-cp)+0.06*cp)   # fallback ~80% early -> 6% late
        sig_new=max(proj*rel,1.0)
        sig_old=math.sqrt(max(proj_k-o,1))*1.5+4                          # the tight Normal we used before
        # per-bracket probs (normalized over this auction's bracket set)
        pn={};po={}
        for lo,hi in a['brks']:
            pn[(lo,hi)]=bprob(lo,hi,proj,sig_new); po[(lo,hi)]=bprob(lo,hi,proj_k,sig_old)
        tn=sum(pn.values()) or 1; to=sum(po.values()) or 1
        for (lo,hi) in a['brks']:
            won=1 if (lo<=a['final']<=hi) else 0
            NEW.append((pn[(lo,hi)]/tn,won)); OLD.append((po[(lo,hi)]/to,won))
        if proj>0: ratio_hist[cp].append(a['final']/proj)

def calib(pairs,label):
    p=np.array([x[0] for x in pairs]); y=np.array([x[1] for x in pairs])
    brier=float(np.mean((p-y)**2))
    print(f"\n{label}  (n={len(p)} bracket-predictions, Brier={brier:.3f})")
    print(f"  {'predicted band':<16}{'n':>6}{'mean predicted':>16}{'ACTUAL win rate':>18}")
    for lo,hi in [(0,.05),(.05,.15),(.15,.30),(.30,.50),(.50,.75),(.75,1.01)]:
        m=(p>=lo)&(p<hi)
        if m.sum()<3: continue
        print(f"  {(f'{lo*100:.0f}-{hi*100:.0f}%'):<16}{m.sum():>6}{p[m].mean()*100:>15.0f}%{y[m].mean()*100:>17.0f}%")
    return brier
bo=calib(OLD,"OLD MODEL  (naive Kalman + tight Normal) - what the losing backtest used")
bn=calib(NEW,"NEW MODEL  (time-weighted Kalman/AccrualCurve ensemble + empirical wide band)")
print(f"\nBrier: OLD {bo:.3f} -> NEW {bn:.3f}  ({'BETTER' if bn<bo else 'worse'}; lower=better)")
print("Calibrated = 'mean predicted' column ~= 'ACTUAL win rate' column. OLD is far above the line (overconfident); NEW should track it.")
