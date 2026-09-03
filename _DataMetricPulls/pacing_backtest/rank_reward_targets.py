# -*- coding: utf-8 -*-
"""Rank the open reward markets for our reward-farm engine: est $/day TO US = daily_rate * our_share,
where our_share = our_notional/(our_notional+book_liquidity) (thin book -> we dominate -> bigger cut),
tagged by TOXICITY (adverse-selection risk). Low/med toxicity + high share-adjusted yield = best fit."""
import pandas as pd, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
df=pd.read_csv('audit_out3/reward_market_scan.csv')
CAP=5000.0
df['our_share']=CAP/(CAP+df['liq'].clip(lower=1))
df['to_us']=df['rate']*df['our_share']
def tox(q):
    s=str(q).lower()
    if any(k in s for k in ['(bo3)','(bo1)','(bo5)','cs2','lol:',' vs ','vs.']): return 'HIGH-live'
    if any(k in s for k in ['wti','crude','bitcoin','ethereum','btc','eth','price of','hit (','dip to','reach ','close above','close below']): return 'HIGH-cont'
    if 'temperature' in s or 'highest temp' in s: return 'MED-weather'
    if 'fed' in s or 'interest rate' in s: return 'EVENT-fed'
    if any(k in s for k in ['invade','ceasefire','withdraw','war ','strait','hormuz','signed into law','act ','sanction','nuclear','treaty']): return 'LOW-geo'
    if any(k in s for k in ['win the','election','president','play for','nominee','confirmed','governor','senate']): return 'LOW-slow'
    return 'other'
df['toxicity']=df['q'].map(tox)
df['days_left']=(pd.to_datetime(df['end'],errors='coerce')-pd.Timestamp('2026-07-22')).dt.days
fmt={'our_share':'{:.0%}'.format,'to_us':'{:.0f}'.format,'liq':'{:.0f}'.format,'rate':'{:.0f}'.format}
good=df[df['toxicity'].isin(['LOW-geo','LOW-slow','MED-weather','EVENT-fed'])].sort_values('to_us',ascending=False)
print('TOP 22 TARGETS by est $/day TO US (cap $5k), low/med toxicity only:')
print(good[['q','rate','liq','our_share','to_us','toxicity','days_left']].head(22).to_string(index=False,formatters=fmt))
print('\nBY TOXICITY BUCKET (n markets, total daily pool $, mean est $/day-to-us at $5k cap):')
g=df.groupby('toxicity').agg(n=('rate','size'),total_pool=('rate','sum'),mean_to_us=('to_us','mean')).sort_values('mean_to_us',ascending=False)
print(g.round(0).to_string())
# a diversified basket: take the best low/med-toxicity target per family, sum est $/day
print('\nDIVERSIFIED FARM BASKET (best few low-tox targets, est combined $/day to us at $5k each):')
basket=good.head(8)
print(f"  {len(basket)} markets | combined est ${basket['to_us'].sum():.0f}/day to us | ${basket['to_us'].sum()*30:.0f}/month (pre adverse-selection)")
