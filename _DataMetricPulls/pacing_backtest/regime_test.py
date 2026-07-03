"""Does layering the EARLY-BURST regime onto our model help, and does it beat the MARKET?
At a mid checkpoint (morning observed, rest unknown) we detect a burst (first-6h rate >> the
walk-forward prior rate) and project the remainder with the BURST rate (persistence) instead of
the shrunk-to-prior Kalman rate. We score MAE vs actual for: Kalman baseline, Kalman+Regime, and
the MARKET's implied final, split by burst vs normal. Edge only if Regime beats BOTH in bursts.
Walk-forward priors (p['e']<s); market/actual for scoring only. Obeys BACKTEST_RULES.md."""
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
def bcenter(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return max(0,int(l[1:])-20)
        if l.endswith('+'): return int(l[:-1])+20
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
    sel.append(dict(slug=a.auction_slug,dur=dur,s=s,e=e,actual=obs(s,e)))
sel=sorted(sel,key=lambda x:x['s'])

def krate(o,eh,rates):
    if not rates: return o/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)
def market_implied(a,t):
    br=[(b,bcenter(b)) for b in buckets_by.get(a['slug'],[]) if (a['slug'],b) in pidx and bcenter(b) is not None]
    pr={b:price_at(a['slug'],b,t) for b,_ in br}; pr={b:v for b,v in pr.items() if v}
    if len(pr)<3: return None
    tot=sum(pr.values()); cen=dict(br)
    return sum((pr[b]/tot)*cen[b] for b in pr)

for frac,lab in [(0.35,'35% elapsed'),(0.5,'50% elapsed')]:
    res={'Kalman':{'burst':[],'normal':[]},'Regime':{'burst':[],'normal':[]},'Market':{'burst':[],'normal':[]}}
    nb=0
    for a in sel:
        s,e,act=a['s'],a['e'],a['actual']; total=(e-s)/3600; eh=total*frac
        t=int(s+eh*3600); o=obs(s,t); hl=total-eh
        priors=[p['actual']/((p['e']-p['s'])/3600) for p in sel if p['e']<s and p['e']>p['s']]
        if not priors or o<=0: continue
        base_rate=float(np.mean(priors))
        early_h=min(6,eh); early_rate=obs(s,int(s+early_h*3600))/max(early_h,1)
        burst = early_rate > 1.4*base_rate
        kr=krate(o,eh,priors)
        kal=o+kr*hl
        recent_rate=obs(int(t-6*3600),t)/6.0
        reg=o+max(kr,recent_rate)*hl if burst else kal    # regime: project remainder with the burst rate
        mk=market_implied(a,t)
        g='burst' if burst else 'normal'
        if burst: nb+=1
        res['Kalman'][g].append(abs(kal-act)); res['Regime'][g].append(abs(reg-act))
        if mk is not None: res['Market'][g].append(abs(mk-act))
    print(f"\n=== checkpoint {lab}  (bursts: {nb}/{len(sel)} auctions) - mean abs error of the final-count estimate ===")
    print(f"{'model':<10}{'BURST auctions':>16}{'NORMAL auctions':>17}")
    for m in ['Kalman','Regime','Market']:
        b=res[m]['burst']; n=res[m]['normal']
        print(f"{m:<10}{(np.mean(b) if b else float('nan')):>15.1f}{(np.mean(n) if n else float('nan')):>17.1f}")
