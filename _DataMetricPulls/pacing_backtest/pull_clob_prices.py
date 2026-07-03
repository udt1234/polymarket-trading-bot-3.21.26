"""Pull dense per-bracket price history (Polymarket CLOB /prices-history, free) for every
current-structure auction. Saves clob_prices.parquet -> the real price source for the trade sim."""
import sys, json, time, urllib.request, urllib.parse, urllib.error
import pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'; OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'

auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True); auc['end_utc']=pd.to_datetime(auc['end_utc'],utc=True)
cur = auc[(auc.duration_type.isin(['2-day','7-day'])) & (auc.winning_bucket!='')
          & (~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))].copy()
cur = cur[((cur.duration_type=='7-day') & (cur.start_utc>=pd.Timestamp('2025-09-05',tz='UTC'))) |
          ((cur.duration_type=='2-day') & (cur.start_utc>=pd.Timestamp('2026-01-05',tz='UTC')))]
print(f"auctions to pull: {len(cur)}")

def prices_history(token, s, e, fid=1):
    p={'market':str(token),'startTs':s,'endTs':e,'fidelity':fid}
    url='https://clob.polymarket.com/prices-history?'+urllib.parse.urlencode(p)
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    for att in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read()).get('history',[])
        except urllib.error.HTTPError as e2:
            if e2.code in (429,500,502,503): time.sleep(2*(att+1)); continue
            return []
        except Exception: time.sleep(1.5); continue
    return []

rows=[]; nreq=0
cur=cur.sort_values('start_utc').reset_index(drop=True)
for i,r in cur.iterrows():
    try: tokmap=json.loads(r['bracket_yes_token_ids'])
    except Exception: continue
    s=int(r['start_utc'].timestamp())-3600; e=int(r['end_utc'].timestamp())+3600
    got=0
    for bucket,token in tokmap.items():
        h=prices_history(token,s,e,1); nreq+=1
        for pt in h:
            rows.append({'auction_slug':r['auction_slug'],'bucket':bucket,'t':pt['t'],'price':pt['p']})
        got+=len(h)
        time.sleep(0.25)
    if i%10==0 or i==len(cur)-1:
        print(f"  {i+1}/{len(cur)} {r['auction_slug'][:40]} (+{got} pts, {nreq} reqs, {len(rows)} total)", flush=True)

df=pd.DataFrame(rows)
df.to_parquet(OUT/'clob_prices.parquet', index=False)
print(f"\nDONE: {len(df)} price points across {df.auction_slug.nunique()} auctions, {nreq} requests")
print(f"  saved: {OUT/'clob_prices.parquet'}")
