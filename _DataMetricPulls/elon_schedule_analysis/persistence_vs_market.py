"""DECISIVE TEST: is the day/week regime-persistence signal mispriced at auction OPEN,
or already baked into the market price?

For each standard 7-day Elon tweet auction:
  window = [start_date 12:00 ET, +7d)   (noon-ET rule)
  realized        = counted tweets in window (clean X-API, counts_main_feed)
  market_open_mean= implied E[count] from bucket prices AT window_start (pure prior, 0 counted yet)
  persist_pred    = counted tweets in the trailing 7d BEFORE window_start (naive momentum prior)
Then: how good is each prior, and does persistence add info BEYOND the market price?
"""
import pandas as pd, numpy as np, re, calendar
from datetime import datetime
ET='America/New_York'

# ---- tweets ----
tw=pd.read_parquet('_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet')
tw['et']=pd.to_datetime(tw['ts_utc'],utc=True,format='ISO8601').dt.tz_convert(ET)
tw=tw[tw['counts_main_feed']==True].sort_values('et')
ts=tw['et']
def count_between(a,b):  # a,b tz-aware ET
    return int(((ts>=a)&(ts<b)).sum())

# ---- prices ----
pr=pd.read_parquet('_DataMetricPulls/pacing_backtest/clob_prices.parquet')
pr['t']=pd.to_datetime(pr['t'],unit='s',utc=True)

MONTHS={m.lower():i for i,m in enumerate(calendar.month_name) if m}
def parse_window(slug):
    # elon-musk-of-tweets-september-5-12  OR  ...-september-9-september-16
    body=slug.replace('elon-musk-of-tweets-','')
    toks=body.split('-')
    # find month tokens
    mi=[i for i,t in enumerate(toks) if t in MONTHS]
    if not mi: return None
    m1=MONTHS[toks[mi[0]]]; d1=int(toks[mi[0]+1])
    if len(mi)>=2:
        m2=MONTHS[toks[mi[1]]]; d2=int(toks[mi[1]+1])
    else:
        m2=m1; d2=int(toks[mi[0]+2])
    # infer years: data spans Sep2025..Jun2026
    y1=2025 if m1>=9 else 2026
    y2=2025 if m2>=9 else 2026
    if m2<m1: y2=y1+1 if y1==2025 else y2  # dec->jan wrap
    if m1==12 and m2==1: y2=2026
    try:
        s=pd.Timestamp(y1,m1,d1,12,0,tz=ET); e=pd.Timestamp(y2,m2,d2,12,0,tz=ET)
    except Exception: return None
    if e<=s: return None
    return s,e

def midpoint(b):
    b=b.strip()
    if b.endswith('+'):
        lo=int(re.findall(r'\d+',b)[0]); return lo+10.0
    if b.startswith('<') or b.startswith('under'):
        hi=int(re.findall(r'\d+',b)[0]); return max(hi-10.0,0)
    nums=re.findall(r'\d+',b)
    if len(nums)>=2: return (int(nums[0])+int(nums[1]))/2
    if len(nums)==1: return float(nums[0])
    return np.nan

rows=[]
for slug,grp in pr.groupby('auction_slug'):
    w=parse_window(slug)
    if not w: continue
    s,e=w; dur=(e-s).days
    if dur!=7: continue                      # standard weekly only
    realized=count_between(s,e)
    if realized==0: continue
    persist=count_between(s-pd.Timedelta(days=7), s)   # trailing 7d prior
    persist14=count_between(s-pd.Timedelta(days=14), s)/2
    # price per bucket AT window_start (last tick <= s)
    gg=grp[grp['t']<=s]
    if gg.empty: continue
    last=gg.sort_values('t').groupby('bucket').tail(1)
    last=last.assign(mid=last['bucket'].map(midpoint)).dropna(subset=['mid'])
    p=last['price'].clip(0,1).values; mids=last['mid'].values
    if p.sum()<=0: continue
    w_=p/p.sum()
    mkt_mean=float((w_*mids).sum())
    rows.append(dict(slug=slug,start=s,realized=realized,mkt=mkt_mean,
                     persist=persist,persist14=persist14,nbuck=len(last),psum=float(p.sum())))
R=pd.DataFrame(rows).sort_values('start').reset_index(drop=True)
print('standard 7-day auctions tested:',len(R))
print(R[['start','realized','mkt','persist','psum','nbuck']].to_string())

def corr(a,b):
    m=np.isfinite(a)&np.isfinite(b); return np.corrcoef(a[m],b[m])[0,1]
re_=R['realized'].values; mk=R['mkt'].values; pe=R['persist'].values
print('\n--- prior quality (corr with realized) ---')
print('market_open_mean : r=%.3f  MAE=%.1f'%(corr(re_,mk), np.mean(np.abs(re_-mk))))
print('persist (prev 7d): r=%.3f  MAE=%.1f'%(corr(re_,pe), np.mean(np.abs(re_-pe))))
print('persist14 avg*7  : r=%.3f'%corr(re_,R['persist14'].values*1))

# incremental info: does persistence beat the market price?
import numpy as np
X=np.column_stack([np.ones(len(R)),mk,pe]); y=re_
beta,*_=np.linalg.lstsq(X,y,rcond=None)
resid=y-X@beta
print('\n--- regression realized ~ 1 + market + persist ---')
print('betas: intercept %.2f  market %.3f  persist %.3f'%(beta[0],beta[1],beta[2]))
# does market already contain persist? regress persist->market resid
Xm=np.column_stack([np.ones(len(R)),mk]); bm,*_=np.linalg.lstsq(Xm,y,rcond=None)
r2_m=1-np.var(y-Xm@bm)/np.var(y); r2_full=1-np.var(resid)/np.var(y)
print('R^2 market-only=%.3f  R^2 market+persist=%.3f  (gain=%.3f)'%(r2_m,r2_full,r2_full-r2_m))

# EV test: sign of (persist - market). If persist>market, does realized>market more often?
R['edge']=R['persist']-R['mkt']; R['err']=R['realized']-R['mkt']
hi=R[R['edge']>5]; lo=R[R['edge']<-5]
print('\n--- directional edge test (does persist disagreeing w/ market predict realized?) ---')
print('when persist>>market (+5): market under-shot realized by mean %.1f (n=%d)'%(hi['err'].mean(),len(hi)))
print('when persist<<market (-5): market over-shot  realized by mean %.1f (n=%d)'%(lo['err'].mean(),len(lo)))
print('corr(persist-market , realized-market) = %.3f'%corr(R['edge'].values,R['err'].values))
R.to_csv('_DataMetricPulls/elon_schedule_analysis/persistence_vs_market_results.csv',index=False)
