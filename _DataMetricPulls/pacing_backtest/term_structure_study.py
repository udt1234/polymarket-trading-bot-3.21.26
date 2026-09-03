# -*- coding: utf-8 -*-
"""TERM-STRUCTURE / CALENDAR relative-value study (market-neutral, NO forecasting).
For every (7-day market that fully contains a 2-day market) pair with pmxt prices, at each hourly bucket
compute each market's MARKET-IMPLIED expected tweet count (price-weighted center of its brackets), convert
to an implied tweets/HOUR rate, and measure the DIVERGENCE between the short-window rate and the long-window
rate over the overlapping days. Then test: (a) how big/persistent is the divergence, (b) does it MEAN-REVERT
(the thing a maker captures), (c) which side is 'right' vs the realized rate. This is the pros' calendar
trade: you are neutral on Elon's actual behavior, long the market's internal inconsistency."""
import glob, os, sys, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; PMX=ROOT+"/_DataMetricPulls/pmxt_pulled"
OUT=ROOT+"/_DataMetricPulls/pacing_backtest/audit_out3"; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64')
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def bmid(l):
    r=pbk(l);
    if r is None: return None
    lo,hi=r; return lo+12.0 if hi>=10**9 else ((hi+1)/2.0 if lo==0 else (lo+hi)/2.0)
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-')
    mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
PMS=int(pd.Timestamp(datetime(2026,4,13,tzinfo=ET)).timestamp()); PME=int(pd.Timestamp(datetime(2026,6,23,tzinfo=ET)).timestamp())
def rows(dur):
    out=[]
    for _,a in auc.iterrows():
        if a.duration_type!=dur or str(a.confidence) not in ('high','medium'): continue
        try: s,e=noon(a.auction_slug)
        except: continue
        if s<PMS or e>PME: continue
        tok=a.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else (dict(tok) if tok is not None else {})
        if not tok: continue
        out.append({'slug':a.auction_slug,'s':s,'e':e,'win':str(a.winning_bucket),'tok':tok})
    return out
d2=rows('2-day'); d7=rows('7-day')
def load_prices(m):
    s,e=m['s'],m['e']; fs=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: fs+=glob.glob(PMX+f"/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    fs=sorted(set(fs))
    if not fs: return None
    t2l={str(v):k for k,v in m['tok'].items()}; tl='('+','.join("'"+str(v)+"'" for v in m['tok'].values())+')'
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
    px=con.execute(f"""SELECT ts,CAST(asset_id AS VARCHAR) aid,best_bid,best_ask FROM read_parquet({arr},union_by_name=true)
        WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {tl} AND best_ask>0 AND best_ask<1 AND best_bid>0 AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if px.empty: return None
    px['lab']=px.aid.map(t2l); px=px[px.lab.notna()]
    return {l:{'ts':g.ts.to_numpy().astype('int64'),'mid':((g.best_bid+g.best_ask)/2).to_numpy(float)} for l,g in px.groupby('lab')}
def implied_center(Bk,tms):
    num=den=0.0
    for l,d in Bk.items():
        bm=bmid(l)
        if bm is None: continue
        i=np.searchsorted(d['ts'],tms,'right')-1
        if i>=0: m=d['mid'][i]; num+=m*bm; den+=m
    return (num/den) if den>0 else None
# ---- build the term-structure panel ----
recs=[]
for m7 in d7:
    Bk7=load_prices(m7)
    if not Bk7: continue
    inside=[m2 for m2 in d2 if m2['s']>=m7['s'] and m2['e']<=m7['e']]
    for m2 in inside:
        Bk2=load_prices(m2)
        if not Bk2: continue
        s2,e2=m2['s'],m2['e']; s7,e7=m7['s'],m7['e']
        # realized rates (ground truth, for scoring only)
        real7=obs(s7,e7)/((e7-s7)/3600.0); real2=obs(s2,e2)/((e2-s2)/3600.0)
        # walk the 2-day window hourly; both markets are live here
        for hh in range(0,int((e2-s2)/3600)):
            tms=(s2+hh*3600)*1000
            c7=implied_center(Bk7,tms); c2=implied_center(Bk2,tms)
            if c7 is None or c2 is None: continue
            # implied REMAINING rate for each market from THIS instant
            el7=(s2+hh*3600-s7)/3600.0; rem7=(e7-(s2+hh*3600))/3600.0
            el2=hh; rem2=(e2-(s2+hh*3600))/3600.0
            o7=obs(s7,s2+hh*3600); o2=obs(s2,s2+hh*3600)
            if rem7<1 or rem2<1: continue
            rate7=(c7-o7)/rem7   # tweets/hr the 7-day market implies for the rest of ITS window
            rate2=(c2-o2)/rem2   # tweets/hr the 2-day market implies for the rest of ITS window
            recs.append({'pair':m7['slug'][-11:]+'|'+m2['slug'][-11:],'s2':s2,'hh':hh,'rem2':rem2,
                         'c7':c7,'c2':c2,'rate7':rate7,'rate2':rate2,'drate':rate2-rate7,
                         'real2':real2,'real7':real7,'real_rate_rem2':obs(s2+hh*3600,e2)/max(rem2,1e-6)})
df=pd.DataFrame(recs)
if df.empty:
    print("no overlapping priced panel built"); sys.exit(0)
df.to_csv(OUT+"/term_structure_panel.csv",index=False)
print(f"panel rows: {len(df)} across {df.pair.nunique()} overlapping pairs")
print(f"\nimplied REMAINING-rate divergence (2day_rate - 7day_rate), tweets/hr:")
print(f"  mean {df['drate'].mean():+.2f} | std {df['drate'].std():.2f} | median {df['drate'].median():+.2f} | p10 {df['drate'].quantile(.1):+.2f} p90 {df['drate'].quantile(.9):+.2f}")
print(f"  |div|>1.0/hr on {100*(df['drate'].abs()>1).mean():.0f}% of hours ; |div|>2.0/hr on {100*(df['drate'].abs()>2).mean():.0f}%")
# WHICH side is right? when 2day rate > 7day rate, is the realized remaining 2-day rate closer to which?
df['err_if_trust2']=(df.rate2-df.real_rate_rem2).abs(); df['err_if_trust7']=(df.rate7-df.real_rate_rem2).abs()
print(f"\nvs REALIZED remaining 2-day rate: trust-2day MAE {df.err_if_trust2.mean():.2f}/hr | trust-7day MAE {df.err_if_trust7.mean():.2f}/hr | midpoint MAE {((df[['rate2','rate7']].mean(1)-df.real_rate_rem2).abs()).mean():.2f}/hr")
# MEAN-REVERSION of the divergence: does a big |div| shrink over the next 6h within the same pair?
df=df.sort_values(['pair','s2','hh'])
rev=[]
for (p,s2),g in df.groupby(['pair','s2']):
    g=g.reset_index(drop=True)
    for i in range(len(g)-6):
        d0=g['drate'].iloc[i]; d6=g['drate'].iloc[i+6]
        if abs(d0)>1.0: rev.append((abs(d0),abs(d6),1 if abs(d6)<abs(d0) else 0))
if rev:
    r=pd.DataFrame(rev,columns=['d0','d6','shrank']);
    print(f"\nMEAN-REVERSION: when |div|>1/hr, 6h later it shrank {100*r.shrank.mean():.0f}% of the time; mean |div| {r.d0.mean():.2f} -> {r.d6.mean():.2f}/hr")
# rough tradeable proxy: the divergence in COUNT terms over the 2-day remaining window
df['div_count']=df['drate']*df['rem2']
print(f"\ndivergence in COUNT terms (rate_div x remaining 2d hours): mean |{df.div_count.abs().mean():.1f}| tweets ; that is the size of the bracket disagreement a calendar maker straddles")
