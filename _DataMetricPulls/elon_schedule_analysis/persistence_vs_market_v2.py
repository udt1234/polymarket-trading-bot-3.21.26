"""v2 - clean the market measurement before trusting any edge.
Compute market implied E[count] at a cutoff with COVERAGE requirements, and
validate the extraction by also measuring mid-window (should track realized well).
"""
import pandas as pd, numpy as np, re, calendar
ET='America/New_York'
tw=pd.read_parquet('_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet')
tw['et']=pd.to_datetime(tw['ts_utc'],utc=True,format='ISO8601').dt.tz_convert(ET)
tw=tw[tw['counts_main_feed']==True].sort_values('et'); ts=tw['et']
cb=lambda a,b:int(((ts>=a)&(ts<b)).sum())
pr=pd.read_parquet('_DataMetricPulls/pacing_backtest/clob_prices.parquet')
pr['t']=pd.to_datetime(pr['t'],unit='s',utc=True)
MONTHS={m.lower():i for i,m in enumerate(calendar.month_name) if m}
def parse_window(slug):
    toks=slug.replace('elon-musk-of-tweets-','').split('-')
    mi=[i for i,t in enumerate(toks) if t in MONTHS]
    if not mi: return None
    m1=MONTHS[toks[mi[0]]]; d1=int(toks[mi[0]+1])
    if len(mi)>=2: m2=MONTHS[toks[mi[1]]]; d2=int(toks[mi[1]+1])
    else: m2=m1; d2=int(toks[mi[0]+2])
    y1=2025 if m1>=9 else 2026; y2=2025 if m2>=9 else 2026
    if m1==12 and m2==1: y2=2026
    try: s=pd.Timestamp(y1,m1,d1,12,0,tz=ET); e=pd.Timestamp(y2,m2,d2,12,0,tz=ET)
    except: return None
    return (s,e) if e>s else None
def midpoint(b):
    b=b.strip()
    if b.endswith('+'): lo=int(re.findall(r'\d+',b)[0]); return lo+10.0
    if b.startswith('<') or b.lower().startswith('under'):
        hi=int(re.findall(r'\d+',b)[0]); return max(hi-10.0,0)
    n=re.findall(r'\d+',b)
    return (int(n[0])+int(n[1]))/2 if len(n)>=2 else (float(n[0]) if n else np.nan)

def implied_mean(grp, cutoff, all_buckets, win_h=8):
    """price per bucket = last tick in [cutoff-win_h, cutoff]; require coverage of all_buckets."""
    lo=cutoff-pd.Timedelta(hours=win_h)
    g=grp[(grp['t']<=cutoff)&(grp['t']>=lo)]
    if g.empty: return None
    last=g.sort_values('t').groupby('bucket').tail(1)
    last=last.assign(mid=last['bucket'].map(midpoint)).dropna(subset=['mid'])
    covered=last['bucket'].nunique()/len(all_buckets)
    p=last['price'].clip(0,1).values; s=p.sum()
    if s<=0: return None
    return dict(mean=float(((p/s)*last['mid'].values).sum()), psum=float(s),
               cov=covered, topmid=float(last['mid'].max()))

rows=[]
for slug,grp in pr.groupby('auction_slug'):
    w=parse_window(slug)
    if not w: continue
    s,e=w
    if (e-s).days!=7: continue
    realized=cb(s,e)
    if realized==0: continue
    persist=cb(s-pd.Timedelta(days=7),s)
    allb=grp['bucket'].unique()
    mo=implied_mean(grp,s,allb)                      # at open
    mid=implied_mean(grp,s+pd.Timedelta(days=4),allb) # 4d into 7d window (validation)
    if mo is None: continue
    rows.append(dict(slug=slug,start=s,realized=realized,persist=persist,
        mkt_open=mo['mean'],psum=mo['psum'],cov=mo['cov'],topmid=mo['topmid'],
        mkt_mid=(mid['mean'] if mid else np.nan),mid_psum=(mid['psum'] if mid else np.nan)))
R=pd.DataFrame(rows).sort_values('start').reset_index(drop=True)
corr=lambda a,b:(np.corrcoef(a[m],b[m])[0,1] if (m:=(np.isfinite(a)&np.isfinite(b))).sum()>2 else np.nan)

print('all 7-day auctions:',len(R))
# CLEAN subset: proper partition at open (psum near 1) AND full coverage
C=R[(R['psum'].between(0.85,1.20))&(R['cov']>=0.95)].copy()
print('CLEAN-open subset (psum in .85-1.2 & cov>=.95):',len(C))
print('  frac of realized ABOVE top listed bucket (truncation):',
      round((R['realized']>R['topmid']).mean(),3),'| in clean:',round((C['realized']>C['topmid']).mean(),3))

for name,D in [('ALL',R),('CLEAN',C)]:
    if len(D)<5: continue
    re_,mk,pe=D['realized'].values,D['mkt_open'].values,D['persist'].values
    print(f'\n=== {name} n={len(D)} ===')
    print('  market_open vs realized : r=%.3f MAE=%.1f'%(corr(re_,mk),np.mean(np.abs(re_-mk))))
    print('  persist(prev7d) vs real : r=%.3f MAE=%.1f'%(corr(re_,pe),np.mean(np.abs(re_-pe))))
    print('  VALIDATION mkt_mid(4d in) vs realized: r=%.3f'%corr(re_,D['mkt_mid'].values))
    # regression realized ~ market + persist
    X=np.column_stack([np.ones(len(D)),mk,pe]); b,*_=np.linalg.lstsq(X,re_,rcond=None)
    r2f=1-np.var(re_-X@b)/np.var(re_)
    Xm=np.column_stack([np.ones(len(D)),mk]); bm,*_=np.linalg.lstsq(Xm,re_,rcond=None)
    r2m=1-np.var(re_-Xm@bm)/np.var(re_)
    print('  reg betas mkt=%.2f persist=%.2f | R2 mkt-only=%.3f  +persist=%.3f (gain %.3f)'%(b[1],b[2],r2m,r2f,r2f-r2m))
R.to_csv('_DataMetricPulls/elon_schedule_analysis/persistence_vs_market_v2.csv',index=False)
print('\nsaved v2 csv')
