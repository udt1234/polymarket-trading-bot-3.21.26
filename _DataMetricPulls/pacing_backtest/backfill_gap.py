"""Fill Sept 1 -> Sept 18 2025 gap, merge into the existing backfill, re-save + update Drive file."""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
import pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
ELON_ID = '44196397'
BEARER = next(l.split('=',1)[1].strip() for l in open(ROOT/'.env', encoding='utf-8') if l.startswith('X_BEARER_TOKEN='))
START='2025-09-01T00:00:00Z'; END='2025-09-18T01:00:00Z'   # overlap existing start (Sep17 19:25), dedup handles it
print(f"gap pull: {START} -> {END}")

def get_page(token=None):
    p={'query':f'from:{ELON_ID}','start_time':START,'end_time':END,'max_results':'500',
       'tweet.fields':'created_at,referenced_tweets,in_reply_to_user_id,conversation_id,public_metrics,lang'}
    if token: p['next_token']=token
    url='https://api.x.com/2/tweets/search/all?'+urllib.parse.urlencode(p)
    req=urllib.request.Request(url, headers={'Authorization':f'Bearer {BEARER}'})
    for att in range(7):
        try:
            with urllib.request.urlopen(req) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(8*(att+1)); continue
            print("HTTP",e.code,e.read().decode()[:200]); raise
    raise RuntimeError("retries")

rows, token, pages = [], None, 0
while True:
    b=get_page(token); rows+=b.get('data',[]); pages+=1
    token=b.get('meta',{}).get('next_token')
    if not token: break
    time.sleep(1.1)
print(f"pulled {len(rows)} raw tweets in {pages} pages (~${len(rows)*0.005:.2f})")

def snow_ms(t): return (int(t)>>22)+1288834974657
def classify(t):
    refs=[r['type'] for r in t.get('referenced_tweets',[])]
    return 'repost' if 'retweeted' in refs else 'quote' if 'quoted' in refs else 'reply' if 'replied_to' in refs else 'original'
recs=[]
for t in rows:
    ty=classify(t); irt=str(t.get('in_reply_to_user_id')); sr=(ty=='reply' and irt==ELON_ID)
    pm=t.get('public_metrics',{}) or {}; ms=snow_ms(t['id'])
    recs.append({'tweet_id':t['id'],'ms':ms,'ts_utc':datetime.fromtimestamp(ms/1000,tz=timezone.utc).isoformat(),
        'created_at':t.get('created_at'),'type':ty,'self_reply':sr,'in_reply_to':irt if irt!='None' else '',
        'conversation_id':str(t.get('conversation_id')),'counts_main_feed':ty in ('original','quote','repost') or sr,
        'lang':t.get('lang'),'like':pm.get('like_count'),'rt':pm.get('retweet_count'),'reply':pm.get('reply_count'),
        'quote':pm.get('quote_count'),'impr':pm.get('impression_count'),'text':(t.get('text') or '').replace('\n',' ')[:280]})
new=pd.DataFrame(recs)

pq=OUT/'elon_backfill_2025-09_to_now.parquet'; csv=OUT/'elon_backfill_2025-09_to_now.csv'
old=pd.read_parquet(pq); before=len(old)
df=pd.concat([old,new],ignore_index=True).drop_duplicates('tweet_id').sort_values('ms').reset_index(drop=True)
df.to_parquet(pq,index=False); df.to_csv(csv,index=False,encoding='utf-8')
print(f"\nmerged: {before} + {len(new)} new = {len(df)} unique  (+{len(df)-before} added)")
print(f"  span: {df.ts_utc.min()} -> {df.ts_utc.max()}")
print(f"  counts_main_feed=True: {int(df.counts_main_feed.sum())}")

# update the SAME Drive file (keeps Sir's link valid)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/drive'], subject='darwin@xagency.com')
drive=build('drive','v3',credentials=creds)
FID='1hfmm4AGXD7yE_elMy5g1EN-CRIjOcsFs'
drive.files().update(fileId=FID, media_body=MediaFileUpload(str(csv),mimetype='text/csv',resumable=True),
    supportsAllDrives=True).execute()
print(f"  Drive file updated (same link): https://drive.google.com/file/d/{FID}/view")
