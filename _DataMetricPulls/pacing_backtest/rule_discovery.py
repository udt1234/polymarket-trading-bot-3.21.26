import sys, numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
CANON = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\canonical')

posts = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'posts/elonmusk').glob('*.parquet'))], ignore_index=True)
posts['ts_utc'] = pd.to_datetime(posts['ts_utc'], utc=True)
print(f'raw posts: {len(posts)},  distinct post_id: {posts["post_id"].nunique()}  -> duplicates: {len(posts)-posts["post_id"].nunique()}')
posts = posts.drop_duplicates('post_id').sort_values('ts_utc').reset_index(drop=True)
ts = (posts['ts_utc'].astype('int64')//10**9).to_numpy()
is_reply = posts['is_reply'].to_numpy(); is_repost = posts['is_repost'].to_numpy(); is_quote = posts['is_quote'].to_numpy()

auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
auc['start_utc'] = pd.to_datetime(auc['start_utc'], utc=True); auc['end_utc'] = pd.to_datetime(auc['end_utc'], utc=True)
clean = auc[(auc['confidence']=='high') & (auc['duration_type'].isin(['2-day','7-day','monthly'])) & (auc['winning_bucket']!='')].copy()
clean = clean[~clean['auction_slug'].str.contains('arch-|higher-bra|lower-bra', regex=True)]  # drop odd split markets

def parse_bucket(lbl):
    lbl=str(lbl).strip()
    try:
        if lbl.startswith('<'): return (0, int(lbl[1:])-1)
        if lbl.endswith('+'): return (int(lbl[:-1]), None)
        if '-' in lbl: a,b=lbl.split('-'); return (int(a),int(b))
        return (int(lbl),int(lbl))
    except: return None

# candidate counting rules (mask over posts)
RULES = {
    'A_not_reply(CURRENT)': ~is_reply,
    'B_orig+quote(no repost)': (~is_reply)&(~is_repost),
    'C_orig_only': (~is_reply)&(~is_repost)&(~is_quote),
    'D_all_posts': np.ones(len(posts), bool),
    'E_orig+repost(no quote)': (~is_reply)&(~is_quote),
    'F_orig+quote+reply(no repost)': (~is_repost),
}

def count_mask(mask, s, e):
    lo=np.searchsorted(ts,s); hi=np.searchsorted(ts,e)
    return int(mask[lo:hi].sum())

rows=[]
for _,a in clean.iterrows():
    s=int(a['start_utc'].timestamp()); e=int(a['end_utc'].timestamp())
    rg=parse_bucket(a['winning_bucket'])
    if not rg: continue
    lo,hi=rg; hi=hi if hi is not None else 10**9
    rec={'slug':a['auction_slug'],'dur':a['duration_type'],'start':a['start_utc'],'winner':a['winning_bucket']}
    for name,mask in RULES.items():
        c=count_mask(mask,s,e)
        rec[name]=c
        rec[name+'_in']= (lo<=c<=hi)
    rows.append(rec)
d=pd.DataFrame(rows)
d['period']=d['start'].dt.year.astype(str)+'Q'+((d['start'].dt.month-1)//3+1).astype(str)

print(f'\nclean auctions tested: {len(d)}')
print('\n=== INSIDE-bucket rate per rule (higher = rule reproduces official count better) ===')
for name in RULES:
    print(f'  {name:32} {100*d[name+"_in"].mean():5.0f}%   ({d[name+"_in"].sum()}/{len(d)})')

print('\n=== inside-rate by period, CURRENT rule vs best alternative ===')
best = max(RULES, key=lambda n: d[n+'_in'].mean())
print(f'best overall rule: {best}')
g = d.groupby('period').agg(n=('slug','size'),
        cur=('A_not_reply(CURRENT)_in','mean'),
        best=(best+'_in','mean'))
g['cur']=(g['cur']*100).round(0); g['best']=(g['best']*100).round(0)
print(g.to_string())

print('\n=== sample: what each rule counts vs winner (recent monthly) ===')
sm=d[d.dur=='monthly'].tail(6)
cols=['start','winner']+list(RULES.keys())
sm=sm.copy(); sm['start']=sm['start'].dt.date
print(sm[cols].to_string(index=False))
