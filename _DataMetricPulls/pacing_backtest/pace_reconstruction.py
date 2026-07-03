"""RECONSTRUCT THE MARKET'S IMPLIED PACE (the highest-upside, market-agnostic engine).
At each moment we INVERT the bracket prices into the market's own implied distribution of the
final count -> its implied final (fair value) + uncertainty. Then:
  1. Is that implied final the sharpest fair value (vs naive pace, vs actual)?  [calibration]
  2. What RULE does the market follow?  (regress implied_final on count-so-far + naive pace)  [recover the formula]
  3. Do DEVIATIONS from the market's own smooth pace curve mean-revert?  [the tradeable mistake]
This machine is FIGURE-AGNOSTIC: brackets -> implied distribution -> fair value -> trade the
deviations. It transfers to any countable/timestamped/bracketed market (tweets, baseball runs,
weather, box office). Obeys BACKTEST_RULES.md (decision uses prices<=t; actual only scores)."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON=ROOT/'_DataMetricPulls'/'canonical'; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms')
pt=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pt.min()),int(pt.max())
def obs(s,e): return int(np.searchsorted(pt,e)-np.searchsorted(pt,s))
prc=pd.read_parquet(OUT/'clob_prices.parquet')
pidx={}
for (sl,bk),g in prc.sort_values('t').groupby(['auction_slug','bucket']): pidx[(sl,bk)]=(g['t'].to_numpy(),g['price'].to_numpy())
buckets_by=prc.groupby('auction_slug')['bucket'].apply(lambda s:sorted(set(s.dropna()))).to_dict()
def price_at(sl,bk,t):
    a=pidx.get((sl,bk))
    if a is None: return None
    ts,ps=a; i=np.searchsorted(ts,t,side='right')-1
    if i<0: return None
    v=float(ps[i]); return v if 0<v<1 else None
def bcenter(lbl):
    l=str(lbl).strip()
    try:
        if l.startswith('<'): hi=int(l[1:]); return max(0,hi-20)
        if l.endswith('+'): lo=int(l[:-1]); return lo+20
        if '-' in l: a,b=l.split('-'); return (int(a)+int(b))/2
        return float(l)
    except: return None
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
cand=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(auc.confidence.isin(['high','medium']))&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
sel=[]
for _,a in cand.iterrows():
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w; dur=a.duration_type; days=(e-s)/86400
    if dur=='7-day' and not 6.5<=days<=7.6: continue
    if dur=='2-day' and not 1.5<=days<=2.6: continue
    if e>c1 or s<c0+7200: continue
    br=[(b,bcenter(b)) for b in buckets_by.get(a.auction_slug,[]) if (a.auction_slug,b) in pidx and bcenter(b) is not None]
    if len(br)<3 or obs(s,e)<=0: continue
    sel.append(dict(slug=a.auction_slug,dur=dur,s=s,e=e,br=br,actual=obs(s,e)))
sel=sorted(sel,key=lambda x:x['s'])
print(f"auctions: {len(sel)} ({sum(x['dur']=='2-day' for x in sel)} 2d, {sum(x['dur']=='7-day' for x in sel)} 7d)")

rows=[]
for a in sel:
    s,e,br=a['s'],a['e'],a['br']; total=(e-s)/3600
    for hh in range(2,int(total)):
        t=s+hh*3600; hl=(e-t)/3600
        if hl<0.5: continue
        pr={b:price_at(a['slug'],b,t) for b,_ in br}; pr={b:v for b,v in pr.items() if v is not None}
        if len(pr)<3: continue
        tot=sum(pr.values())
        if tot<=0: continue
        prob={b:v/tot for b,v in pr.items()}; cen={b:c for b,c in br}
        imean=sum(prob[b]*cen[b] for b in prob)
        istd=math.sqrt(max(0,sum(prob[b]*(cen[b]-imean)**2 for b in prob)))
        o=obs(s,t); ef=hh/total
        rows.append(dict(slug=a['slug'],dur=a['dur'],hh=hh,ttg=round(hl,1),o=o,ef=ef,implied=imean,istd=istd,naive=o/max(ef,0.02),actual=a['actual']))
D=pd.DataFrame(rows)
print(f"reconstructed snapshots: {len(D)}")

print("\n=== 1) CALIBRATION  (mean abs error of the FINAL-count estimate, by hours-to-go) ===")
print(f"{'ttg band':<10}{'n':>6}{'MKT-implied err':>16}{'naive-pace err':>16}")
D['ttgband']=pd.cut(D.ttg,[0,3,12,24,48,200],labels=['0-3h','3-12h','12-24h','24-48h','48h+'])
for band in ['0-3h','3-12h','12-24h','24-48h','48h+']:
    g=D[D.ttgband==band]
    if not len(g): continue
    print(f"{band:<10}{len(g):>6}{np.mean(np.abs(g.implied-g.actual)):>15.1f}{np.mean(np.abs(g.naive-g.actual)):>16.1f}")

print("\n=== 2) RECOVER THE FORMULA:  implied_final ~ a*count_so_far + b*naive_pace + c ===")
for dur in ['2-day','7-day']:
    g=D[(D.dur==dur)&(D.ef>0.1)&(D.ef<0.95)].dropna()
    if len(g)<50: continue
    X=np.column_stack([g.o, g.naive, np.ones(len(g))]); y=g.implied.to_numpy()
    coef,_,_,_=np.linalg.lstsq(X,y,rcond=None)
    pred=X@coef; r2=1-np.sum((y-pred)**2)/np.sum((y-y.mean())**2)
    print(f"  {dur}:  implied ~= {coef[0]:.2f}*count + {coef[1]:.2f}*naive_pace + {coef[2]:.1f}   (R^2={r2:.3f}, n={len(g)})")

print("\n=== 3) TRADEABLE MISTAKE:  deviations from a CAUSAL (trailing-only) smooth, no look-ahead ===")
rev=[]; devs=[]; fwds=[]
for a in sel:
    g=D[D.slug==a['slug']].sort_values('hh')
    if len(g)<10: continue
    imp=g.implied.to_numpy()
    sm=pd.Series(imp).rolling(6,min_periods=3).median().to_numpy()   # TRAILING window only (known at i)
    for i in range(6,len(imp)-3):
        if not np.isfinite(sm[i]): continue
        dev=imp[i]-sm[i]; fwd=imp[i+3]-imp[i]
        devs.append(dev); fwds.append(fwd)
        if abs(dev)>1.5: rev.append(-np.sign(dev)*fwd/abs(dev))
rev=np.array([x for x in rev if np.isfinite(x)])
dv=np.array(devs); fw=np.array(fwds); m=np.isfinite(dv)&np.isfinite(fw)
corr=np.corrcoef(dv[m],-fw[m])[0,1]   # >0 = a deviation predicts a reversion (the tradeable signal)
print(f"  predictive corr(deviation, next-3h REVERSION) across ALL {int(m.sum())} points: {corr:+.3f}")
print(f"     (>0 = the market's own overshoot reverts and is fadeable; ~0 = efficient even vs itself)")
if len(rev):
    print(f"  on the |deviation|>1.5 subset (n={len(rev)}): median revert-frac {np.median(rev):.2f}  % reverting {100*np.mean(rev>0):.0f}%")
