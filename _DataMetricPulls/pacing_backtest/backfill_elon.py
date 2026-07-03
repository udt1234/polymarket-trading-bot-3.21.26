"""Backfill Elon tweets Sept 2025 -> now via X full-archive API, applying the LOCKED count rule.
Rule: count = original | quote | repost | self-reply(in_reply_to==Elon). Off-feed replies excluded.
Timestamp = snowflake ms. Saves parquet + CSV. Cost guard caps spend.
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
import pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
ELON_ID = '44196397'
BEARER = next(l.split('=',1)[1].strip() for l in open(ROOT/'.env', encoding='utf-8') if l.startswith('X_BEARER_TOKEN='))

START = '2025-09-01T00:00:00Z'
END = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
MAX_TWEETS = 18000      # cost guard: 18000 * $0.005 = $90 hard ceiling
COST_PER = 0.005
print(f"backfill window: {START} -> {END}   (cap {MAX_TWEETS} tweets / ~${MAX_TWEETS*COST_PER:.0f})")

def get_page(token=None):
    p={'query':f'from:{ELON_ID}','start_time':START,'end_time':END,'max_results':'500',
       'tweet.fields':'created_at,referenced_tweets,in_reply_to_user_id,conversation_id,public_metrics,lang'}
    if token: p['next_token']=token
    url='https://api.x.com/2/tweets/search/all?'+urllib.parse.urlencode(p)
    req=urllib.request.Request(url, headers={'Authorization':f'Bearer {BEARER}'})
    for attempt in range(7):
        try:
            with urllib.request.urlopen(req) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            txt=e.read().decode()[:300]
            if e.code==429: w=8*(attempt+1); print(f"  429, sleep {w}s"); time.sleep(w); continue
            if e.code in (402,403) and 'credit' in txt.lower():
                print("  OUT OF CREDITS — stopping gracefully"); return {'_stop':True}
            print("  HTTP",e.code,txt); raise
    raise RuntimeError("retries exhausted")

rows, token, pages = [], None, 0
while True:
    body=get_page(token)
    if body.get('_stop'): break
    rows+=body.get('data',[]); pages+=1
    token=body.get('meta',{}).get('next_token')
    if pages%5==0 or not token:
        print(f"  page {pages}: total={len(rows)}  ~${len(rows)*COST_PER:.2f}")
    if not token: break
    if len(rows)>=MAX_TWEETS: print("  HIT COST CAP — stopping"); break
    time.sleep(1.1)

print(f"\npulled {len(rows)} raw tweets in {pages} pages  (~${len(rows)*COST_PER:.2f})")

def snow_ms(tid): return (int(tid)>>22)+1288834974657
def classify(t):
    refs=[r['type'] for r in t.get('referenced_tweets',[])]
    if 'retweeted' in refs: return 'repost'
    if 'quoted' in refs: return 'quote'
    if 'replied_to' in refs: return 'reply'
    return 'original'

recs=[]
for t in rows:
    ty=classify(t); irt=str(t.get('in_reply_to_user_id'))
    self_reply=(ty=='reply' and irt==ELON_ID)
    counts=ty in ('original','quote','repost') or self_reply   # LOCKED RULE
    pm=t.get('public_metrics',{}) or {}
    ms=snow_ms(t['id'])
    recs.append({'tweet_id':t['id'],'ms':ms,
                 'ts_utc':datetime.fromtimestamp(ms/1000,tz=timezone.utc).isoformat(),
                 'created_at':t.get('created_at'),'type':ty,'self_reply':self_reply,
                 'in_reply_to':irt if irt!='None' else '','conversation_id':str(t.get('conversation_id')),
                 'counts_main_feed':counts,'lang':t.get('lang'),
                 'like':pm.get('like_count'),'rt':pm.get('retweet_count'),
                 'reply':pm.get('reply_count'),'quote':pm.get('quote_count'),
                 'impr':pm.get('impression_count'),
                 'text':(t.get('text') or '').replace('\n',' ')[:280]})
df=pd.DataFrame(recs).drop_duplicates('tweet_id').sort_values('ms').reset_index(drop=True)

pq=OUT/'elon_backfill_2025-09_to_now.parquet'; csv=OUT/'elon_backfill_2025-09_to_now.csv'
df.to_parquet(pq, index=False); df.to_csv(csv, index=False, encoding='utf-8')

print(f"\n=== SAVED {len(df)} unique tweets ===")
print(f"  span: {df.ts_utc.min()} -> {df.ts_utc.max()}")
print(f"  type mix: {df['type'].value_counts().to_dict()}")
print(f"  counts_main_feed=True: {int(df.counts_main_feed.sum())} / {len(df)}")
print(f"  parquet: {pq}")
print(f"  csv:     {csv}")
print(f"  est spend this run: ${len(rows)*COST_PER:.2f}")
