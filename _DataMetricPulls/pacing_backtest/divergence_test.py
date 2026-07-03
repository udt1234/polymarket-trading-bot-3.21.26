"""The last untested Elon edge: our KALMAN (grounded in the real tweet count) vs the MARKET's
implied final (the reverse-pace). When they DISAGREE, who is closer to the actual final, and does
the price revert toward Kalman? If Kalman wins the disagreements, we fade the market toward our
own fair value and hold. Walk-forward Kalman priors (p['e']<s); actual only scores. BACKTEST_RULES."""
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
prc=pd.read_parquet(OUT/'clob_prices.parquet'); pidx={}
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
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
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
    br=[(b,pbk(b),bcenter(b)) for b in buckets_by.get(a.auction_slug,[]) if (a.auction_slug,b) in pidx and pbk(b) and bcenter(b) is not None]
    if len(br)<3 or obs(s,e)<=0: continue
    sel.append(dict(slug=a.auction_slug,dur=dur,s=s,e=e,br=br,winner=str(a.winning_bucket),actual=obs(s,e)))
sel=sorted(sel,key=lambda x:x['s'])
def krate(o,eh,rates):
    if not rates: return o/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)
rows=[]
for a in sel:
    s,e,br=a['s'],a['e'],a['br']; total=(e-s)/3600
    priors=[p['actual']/((p['e']-p['s'])/3600) for p in sel if p['e']<s and p['e']>p['s']]
    if not priors: continue
    for hh in range(3,int(total)):
        t=s+hh*3600; hl=(e-t)/3600
        if hl<0.5: continue
        o=obs(s,t); kal=o+krate(o,hh,priors)*hl
        pr={b:price_at(a['slug'],b,t) for b,_,_ in br}; pr={b:v for b,v in pr.items() if v}
        if len(pr)<3: continue
        tot=sum(pr.values()); mkt=sum((pr[b]/tot)*c for (b,_,c) in br if b in pr)
        mfav=max(pr,key=pr.get); kfav=None
        for b,(lo,hi),_ in br:
            if lo<=round(kal)<=hi: kfav=b; break
        rows.append(dict(slug=a['slug'],dur=a['dur'],hh=hh,ttg=round(hl,1),kal=kal,mkt=mkt,kfav=kfav,mfav=mfav,winner=a['winner'],actual=a['actual']))
D=pd.DataFrame(rows)
print(f"checkpoints: {len(D)}  auctions: {D.slug.nunique()}")
print("\n=== when KALMAN and MARKET disagree, who is closer to the ACTUAL final? ===")
for thr in [3,6,10]:
    g=D[abs(D.kal-D.mkt)>thr].dropna(subset=['kal','mkt'])
    if not len(g): continue
    kwin=(np.abs(g.kal-g.actual)<np.abs(g.mkt-g.actual)).mean()
    print(f"  |Kalman - Market| > {thr:>2}:  n={len(g):>4}  Kalman closer {100*kwin:.0f}% of the time  (50% = no edge)")
print("\n=== bracket-level: in disagreement cases, whose FAVORITE bracket is the winner? ===")
g=D[(D.kfav.notna())&(D.kfav!=D.mfav)]
for band,lohi in [('early (>24h)',(24,999)),('mid (6-24h)',(6,24)),('late (<6h)',(0,6))]:
    gg=g[(g.ttg>lohi[0])&(g.ttg<=lohi[1])]
    if not len(gg): continue
    print(f"  {band:<13} n={len(gg):>4}  Kalman-fav hits {100*(gg.kfav==gg.winner).mean():.0f}%   Market-fav hits {100*(gg.mfav==gg.winner).mean():.0f}%")
print("\n=== does the market PRICE revert toward Kalman after they diverge? (causal, next 3h) ===")
rev=[]
for slug,gg in D.groupby('slug'):
    gg=gg.sort_values('hh'); mk=gg.mkt.to_numpy(); ka=gg.kal.to_numpy()
    for i in range(len(gg)-3):
        d=mk[i]-ka[i]
        if abs(d)>4: rev.append(-np.sign(d)*(mk[i+3]-mk[i])/abs(d))
rev=np.array([x for x in rev if np.isfinite(x)])
if len(rev): print(f"  after |Market-Kalman|>4, market's next-3h move toward Kalman: median {np.median(rev):.2f}  %toward {100*np.mean(rev>0):.0f}%  (n={len(rev)})")
