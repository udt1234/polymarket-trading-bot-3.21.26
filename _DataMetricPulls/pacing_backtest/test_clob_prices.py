import sys, json, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
import pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
CANON = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\canonical')
auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True); auc['end_utc']=pd.to_datetime(auc['end_utc'],utc=True)
r = auc[auc.auction_slug=='elon-musk-of-tweets-june-1-june-3'].iloc[0]
tokmap = json.loads(r['bracket_yes_token_ids'])
print("bracket -> token map keys:", list(tokmap.keys()))
startTs = int(r['start_utc'].timestamp()); endTs = int(r['end_utc'].timestamp())
print(f"window {startTs} -> {endTs}  ({r['start_utc']} -> {r['end_utc']})")

def prices_history(token, s, e, fidelity=1):
    p = {'market': str(token), 'startTs': s, 'endTs': e, 'fidelity': fidelity}
    url = 'https://clob.polymarket.com/prices-history?' + urllib.parse.urlencode(p)
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

for b in ['65-89', '40-64', '90-114']:
    tok = tokmap.get(b)
    try:
        h = prices_history(tok, startTs, endTs, 1).get('history', [])
        if h:
            ts = [pt['t'] for pt in h]
            gaps = [ts[i+1]-ts[i] for i in range(len(ts)-1)]
            mingap = min(gaps) if gaps else None
            print(f"\nbracket {b}: {len(h)} points, min gap={mingap}s")
            print("  first 3:", [(datetime.fromtimestamp(pt['t'],tz=timezone.utc).strftime('%m-%d %H:%M'), pt['p']) for pt in h[:3]])
            print("  last 3: ", [(datetime.fromtimestamp(pt['t'],tz=timezone.utc).strftime('%m-%d %H:%M'), pt['p']) for pt in h[-3:]])
        else:
            print(f"\nbracket {b}: empty history")
    except urllib.error.HTTPError as e:
        print(f"\nbracket {b}: HTTP {e.code} {e.read().decode()[:150]}")
