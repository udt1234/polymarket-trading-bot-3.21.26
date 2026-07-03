"""AccrualCurve pacing model: projected_final = observed / share(elapsed_hours), where share()
is the empirical median fraction of the window's final count accrued by that elapsed hour
(built from generic noon-ET 2-day / 7-day windows). The share curve naturally embeds the
sleep dead-zones (it advances slowly during 4-8am ET). Backtests it (bracket-hit + err%) at
T-1d / T-1h vs Kalman + Linear on the same canonical auctions, walk-forward. Saves share curves."""
import sys, json, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON=ROOT/'_DataMetricPulls'/'canonical'; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms').reset_index(drop=True)
pt=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pt.min()),int(pt.max())
def obs(s,e): return int(np.searchsorted(pt,e)-np.searchsorted(pt,s))

# ---- build share curves from GENERIC noon-ET windows (every day start) ----
# WALK-FORWARD: before_ts caps which windows count (only those that fully CLOSED before it). A
# backtest at auction-start s must call build_share(dur, s) so the curve never peeks at the
# future. before_ts=None = global curve, correct ONLY for live use (at 'now' all history is past).
def build_share(dur_h, before_ts=None):
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12)
    cap=c1 if before_ts is None else min(c1,int(before_ts))
    curves=[]
    d=noon0
    while d.timestamp()+dur_h*3600<=cap:
        s=int(d.timestamp()); e=s+dur_h*3600; final=obs(s,e)
        if final>=5:
            cur=np.array([obs(s,s+h*3600) for h in range(1,dur_h+1)],float)/final
            curves.append(cur)
        d=d+pd.Timedelta(days=1)
    if not curves: return None,0
    M=np.median(np.vstack(curves),axis=0)
    return np.clip(M,1e-3,1.0), len(curves)
# GLOBAL curves = for LIVE use + the json the live pacer reads (legit: 'now' is after all history)
share48,n48=build_share(48); share168,n168=build_share(168)
print(f"share curves built: 2-day from {n48} windows, 7-day from {n168} windows")
print(f"  2-day share @ elapsed h: 6h={share48[5]:.2f} 12h={share48[11]:.2f} 24h={share48[23]:.2f} 36h={share48[35]:.2f} 47h={share48[46]:.2f}")
print(f"  sleep dead-zone check (2-day, hours 16->20 = 4am->8am ET day1): "+" ".join(f"{share48[h]:.3f}" for h in range(15,21)))
json.dump({'share_2day':list(share48),'share_7day':list(share168)},open(OUT/'accrual_share_curves.json','w'))

# ---- auctions ----
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

def kalman_rate(o,eh,rates):
    if not rates: return o/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)
def run(hr):
    R={m:{'2-day':[],'7-day':[]} for m in ['Accrual','Kalman','Linear']}
    E={m:{'2-day':[],'7-day':[]} for m in ['Accrual','Kalman','Linear']}
    wf={}   # walk-forward share curves, cached by auction-start (only windows that closed before s)
    for a in sel:
        s,e=a['s'],a['e']; total=(e-s)/3600; eh=total-hr; lo,hi=a['wb']; act=a['actual']
        if eh<=0.5: continue
        cps=s+int(eh*3600); o=obs(s,cps)
        if s not in wf: wf[s]=(build_share(48,s)[0], build_share(168,s)[0])
        share=wf[s][0] if a['dur']=='2-day' else wf[s][1]
        proj={'Linear':o*total/eh}
        priors=[p['actual']/((p['e']-p['s'])/3600) for p in sel if p['e']<s and p['e']>p['s']]
        proj['Kalman']=o+kalman_rate(o,eh,priors)*hr
        if share is not None:                       # Accrual only when walk-forward history exists
            idx=min(len(share)-1,max(0,int(eh)-1)); proj['Accrual']=o/share[idx]
        for m,pv in proj.items():
            R[m][a['dur']].append(1 if lo<=round(pv)<=hi else 0)
            E[m][a['dur']].append(abs(pv-act)/act*100)
    return R,E
print("\n=== bracket-hit % (and mean err%) by model, T-1d / T-1h ===")
for hr,lab in [(24,'T-1d'),(1,'T-1h')]:
    R,E=run(hr)
    print(f"\n{lab}:")
    print(f"{'model':<9}{'2d hit':>8}{'2d err':>8}{'7d hit':>8}{'7d err':>8}")
    for m in ['Accrual','Kalman','Linear']:
        def f(d,T):
            v=T[m][d]; return (100*np.mean(v)) if v else float('nan')
        print(f"{m:<9}{f('2-day',R):>7.0f}%{np.mean(E[m]['2-day']) if E[m]['2-day'] else 0:>7.0f}%{f('7-day',R):>7.0f}%{np.mean(E[m]['7-day']) if E[m]['7-day'] else 0:>7.0f}%")
