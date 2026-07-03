import sys, pandas as pd, numpy as np
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
pd.set_option('display.max_columns', None); pd.set_option('display.width', 200)
CANON = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\canonical')

auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
pri = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'prices/elonmusk').glob('*.parquet'))], ignore_index=True)

print('=== AUCTIONS columns ===')
print(list(auc.columns))
print('\n=== PRICES columns ===')
print(list(pri.columns))

# pick a high-conf auction and show its bracket set
clean = auc[(auc['confidence']=='high') & (auc['duration_type'].isin(['2-day','7-day','monthly'])) & (auc['winning_bucket']!='')].copy()
print(f'\nclean high-conf auctions: {len(clean)}')
print('\nsample auction rows (slug, duration, winning_bucket):')
print(clean[['auction_slug','duration_type','winning_bucket']].head(8).to_string())

# find the bucket key column in prices
slug = clean.iloc[3]['auction_slug']
print(f'\n=== distinct buckets in PRICES for auction: {slug} ===')
key_candidates = [c for c in pri.columns if 'slug' in c.lower() or 'auction' in c.lower() or 'event' in c.lower()]
print('price key candidates:', key_candidates)
bucket_candidates = [c for c in pri.columns if 'bucket' in c.lower() or 'label' in c.lower() or 'outcome' in c.lower()]
print('bucket col candidates:', bucket_candidates)
if key_candidates and bucket_candidates:
    kc, bc = key_candidates[0], bucket_candidates[0]
    sub = pri[pri[kc]==slug]
    print(f'rows for this auction: {len(sub)}')
    print('distinct buckets:', sorted(sub[bc].dropna().unique().tolist()))

# show all distinct bucket label formats across all prices
if bucket_candidates:
    bc = bucket_candidates[0]
    allb = pri[bc].dropna().unique().tolist()
    print(f'\n=== ALL distinct bucket labels across prices (n={len(allb)}) ===')
    print(sorted(set(str(b) for b in allb))[:60])
