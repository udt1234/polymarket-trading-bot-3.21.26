import sys, numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
pd.set_option('display.max_columns', None); pd.set_option('display.width', 240)
CANON = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\canonical')
posts = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'posts/elonmusk').glob('*.parquet'))], ignore_index=True)

print('=== POSTS columns ===')
for c in posts.columns:
    print(f'  {c:30} {str(posts[c].dtype):12}')

print(f'\ntotal posts: {len(posts)}')
print('\n=== boolean-ish flag distributions ===')
for c in posts.columns:
    if posts[c].dropna().isin([True, False, 0, 1]).all() and posts[c].nunique(dropna=True) <= 3:
        print(f'  {c:30} {posts[c].value_counts(dropna=False).to_dict()}')

# any column that smells like post-type / main-feed / reply-target
print('\n=== candidate type/main-feed columns (sample distinct values) ===')
for c in posts.columns:
    lc = c.lower()
    if any(k in lc for k in ['type','feed','reply','repost','quote','thread','conversation','in_reply','target','kind','count']):
        vals = posts[c].dropna().unique()
        print(f'  {c}: n_unique={posts[c].nunique(dropna=True)}, sample={vals[:6].tolist() if len(vals) else []}')

print('\n=== 6 sample rows (key cols) ===')
keycols = [c for c in posts.columns if any(k in c.lower() for k in
           ['ts_utc','type','reply','repost','quote','feed','counts_for','text','conversation','in_reply'])][:14]
print(posts[keycols].head(6).to_string())
