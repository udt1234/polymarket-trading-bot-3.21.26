import sys, math
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls')
CANON = ROOT/'canonical'; OUT = ROOT/'pacing_backtest'

posts = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'posts/elonmusk').glob('*.parquet'))], ignore_index=True)
posts['ts_utc'] = pd.to_datetime(posts['ts_utc'], utc=True)
counted = posts[posts['counts_for_auction'] == True].sort_values('ts_utc')
post_ts = (counted['ts_utc'].astype('int64')//10**9).to_numpy()
auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
pri = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'prices/elonmusk').glob('*.parquet'))], ignore_index=True)
pri['hour_secs'] = (pd.to_datetime(pri['hour_utc'], utc=True).astype('int64')//10**9)
res = pd.read_csv(OUT/'backtest_full_results.csv'); res['start_dt'] = pd.to_datetime(res['start_utc'], utc=True)
winner_by_slug = auc.set_index('auction_slug')['winning_bucket'].to_dict()
buckets_by_slug = pri.groupby('auction_slug')['bucket'].apply(lambda s: sorted(set(s.dropna()))).to_dict()

def parse_bucket(lbl):
    lbl=str(lbl).strip()
    try:
        if lbl.startswith('<'): return (0, int(lbl[1:])-1)
        if lbl.endswith('+'): return (int(lbl[:-1]), None)
        if '-' in lbl: a,b=lbl.split('-'); return (int(a),int(b))
        return (int(lbl),int(lbl))
    except: return None
def landed(pred, labels):
    for b in labels:
        rg=parse_bucket(b)
        if rg and rg[0] <= pred <= (rg[1] if rg[1] is not None else 1e9): return b
    return '??'
def obs(s,c): return int(np.searchsorted(post_ts,c)-np.searchsorted(post_ts,s))
def mkt_argmax(slug, cp_secs, labels):
    best=None;bp=-1;wp=None
    for b in labels:
        g=pri[(pri.auction_slug==slug)&(pri.bucket==b)&(pri.hour_secs<=cp_secs)]
        if not len(g): continue
        c=float(g.sort_values('hour_secs').iloc[-1]['close'])
        if 0<c<1 and c>bp: bp=c;best=b
    return best,bp

print('=== T-1d spot check: actual vs winner vs model landings ===')
res2=res.sort_values('actual')
sample=pd.concat([res2.head(5), res2.iloc[40:45], res2.tail(5)])
for _,r in sample.iterrows():
    if r.get('Kalman_T1d','')=='' or pd.isna(r.get('Kalman_T1d',np.nan)): continue
    slug=r['auction_slug']; actual=int(r['actual']); winner=winner_by_slug.get(slug)
    labels=buckets_by_slug.get(slug,[]); start=int(r['start_dt'].timestamp())
    cp=start+int((float(r['total_hours'])-24)*3600); o=obs(start,cp)
    mb,mp=mkt_argmax(slug,cp,labels)
    print(f'\n{slug[:42]:42} actual={actual:5} winner={str(winner):8} obs@T-1d={o:5}  nbuckets={len(labels)}')
    print(f'   buckets={labels}')
    for m in ['Linear','Kalman','M4MMPP','M2Hawk']:
        p=float(r[f'{m}_T1d']); print(f'   {m:8} pred={p:7.0f} -> lands {landed(p,labels):8}  {"HIT" if landed(p,labels)==winner else "miss"}')
    print(f'   MARKET argmax={str(mb):8} price={mp:.2f}  {"HIT" if mb==winner else "miss"}')

# bias + bucket-width context
print('\n=== context (T-1d) ===')
errs={m:[] for m in ['Linear','Kalman','M4MMPP','M2Hawk']}
widths=[]; openend=0; ntot=0
for _,r in res.iterrows():
    if r.get('Kalman_T1d','')=='' or pd.isna(r.get('Kalman_T1d',np.nan)): continue
    actual=float(r['actual']); winner=winner_by_slug.get(r['auction_slug']); ntot+=1
    rg=parse_bucket(winner) if winner else None
    if rg:
        if rg[1] is None: openend+=1
        else: widths.append(rg[1]-rg[0]+1)
    for m in errs: errs[m].append(actual-float(r[f'{m}_T1d']))
print(f'auctions={ntot}, winner is open-ended "N+" bracket: {openend} ({100*openend/ntot:.0f}%)')
print(f'median closed-bucket width: {np.median(widths):.0f} tweets')
print('actual count distribution:', {k:int(np.percentile(res.actual,k)) for k in [10,25,50,75,90]})
for m,e in errs.items():
    e=np.array(e); print(f'   {m:8} mean signed err (actual-pred)={e.mean():+.1f}  (negative => model OVER-predicts)')
