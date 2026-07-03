"""Test pull: one resolved 7-day Elon auction via X full-archive API.
Types every tweet, applies xTracker counting rules, validates the count against
the official winning bucket, and dumps raw tweets to a Google Sheet tab.
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
import pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'
ELON_ID = '44196397'
ENV = ROOT/'.env'
BEARER = next(l.split('=',1)[1].strip() for l in open(ENV, encoding='utf-8') if l.startswith('X_BEARER_TOKEN='))

# --- pick target auction: most recent high-conf 7-day with a winner ---
auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
auc['start_utc'] = pd.to_datetime(auc['start_utc'], utc=True); auc['end_utc'] = pd.to_datetime(auc['end_utc'], utc=True)
cand = auc[(auc.duration_type=='7-day') & (auc.winning_bucket!='')
           & (~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra', regex=True))
           & (auc.start_utc >= pd.Timestamp('2025-09-05', tz='UTC'))].copy()
cand['days'] = (cand.end_utc - cand.start_utc).dt.total_seconds()/86400
cand = cand[(cand.days >= 6.5) & (cand.days <= 7.6)].sort_values('end_utc')
print("clean 7-day candidates (tail):")
print(cand[['auction_slug','start_utc','end_utc','days','confidence','winning_bucket']].tail(6).to_string(index=False))
a = cand.iloc[-1]
slug, winner = a['auction_slug'], a['winning_bucket']
start_iso = a['start_utc'].strftime('%Y-%m-%dT%H:%M:%SZ'); end_iso = a['end_utc'].strftime('%Y-%m-%dT%H:%M:%SZ')
print(f"TARGET: {slug}\n  window {start_iso} -> {end_iso}\n  official winner: {winner}")

# --- pull all tweets in window (full-archive search, paginate) ---
def get_page(token=None):
    p = {'query': f'from:{ELON_ID}', 'start_time': start_iso, 'end_time': end_iso,
         'max_results': '500',
         'tweet.fields': 'created_at,referenced_tweets,in_reply_to_user_id,conversation_id,public_metrics,note_tweet,lang'}
    if token: p['next_token'] = token
    url = 'https://api.x.com/2/tweets/search/all?' + urllib.parse.urlencode(p)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {BEARER}'})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt+1); print(f"  429 rate-limit, sleeping {wait}s"); time.sleep(wait); continue
            print("HTTP", e.code, e.read().decode()[:300]); raise
    raise RuntimeError("too many retries")

rows, token, pages = [], None, 0
while True:
    body = get_page(token); pages += 1
    rows.extend(body.get('data', []))
    token = body.get('meta', {}).get('next_token')
    print(f"  page {pages}: +{len(body.get('data', []))}  total={len(rows)}")
    if not token or pages >= 40: break
    time.sleep(1.1)
print(f"pulled {len(rows)} tweets in {pages} pages  (~${len(rows)*0.005:.2f} est)")

# --- type + apply rules ---
def snow_ms(tid): return (int(tid) >> 22) + 1288834974657
def classify(t):
    refs = [r['type'] for r in t.get('referenced_tweets', [])]
    if 'retweeted' in refs: return 'repost'
    if 'quoted' in refs: return 'quote'
    if 'replied_to' in refs: return 'reply'
    return 'original'

recs = []
for t in rows:
    typ = classify(t)
    self_reply = (typ=='reply' and str(t.get('in_reply_to_user_id'))==ELON_ID)
    # xTracker rule: count originals + quotes + reposts + self(main-feed) replies; drop other-replies
    counts = typ in ('original','quote','repost') or self_reply
    recs.append({'ms': snow_ms(t['id']), 'id': t['id'], 'created_at': t.get('created_at'),
                 'type': typ, 'self_reply': self_reply, 'in_reply_to': t.get('in_reply_to_user_id'),
                 'counts_official': counts, 'text': (t.get('text') or '')[:160]})
df = pd.DataFrame(recs).sort_values('ms').reset_index(drop=True)

bd = df['type'].value_counts().to_dict()
n_reply_self = int(df.self_reply.sum()); n_reply_other = int((df.type=='reply').sum()) - n_reply_self
count_official = int(df.counts_official.sum())
count_no_repost = count_official - int((df.type=='repost').sum())
print("\n=== breakdown ===")
print(f"  original={bd.get('original',0)} quote={bd.get('quote',0)} repost={bd.get('repost',0)} "
      f"reply_self={n_reply_self} reply_other={n_reply_other}")
print(f"  COUNT (official rule, incl reposts):  {count_official}   winner={winner}")
print(f"  COUNT (excl reposts):                 {count_no_repost}")

# --- write to Google Sheet ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds = service_account.Credentials.from_service_account_file(
    os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc = build('sheets','v4',credentials=creds)
SHEET_ID = '1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8'; TAB='_X_API_TestPull'
meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID, fields='sheets(properties(title,sheetId))').execute()
titles = [s['properties']['title'] for s in meta['sheets']]
if TAB not in titles:
    svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={'requests':[{'addSheet':{'properties':{'title':TAB}}}]}).execute()
svc.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range=f'{TAB}!A1:Z5000').execute()
header = [[f"X API test pull — {slug}  |  window {start_iso} to {end_iso}  |  official winner {winner}"],
         [f"COUNT official(incl reposts)={count_official}   excl-reposts={count_no_repost}   "
          f"orig={bd.get('original',0)} quote={bd.get('quote',0)} repost={bd.get('repost',0)} reply_self={n_reply_self} reply_other={n_reply_other}"],
         ['ms_timestamp','tweet_id','created_at','type','self_reply','counts_official','text']]
data = header + df[['ms','id','created_at','type','self_reply','counts_official','text']].astype(str).values.tolist()
svc.spreadsheets().values().update(spreadsheetId=SHEET_ID, range=f'{TAB}!A1', valueInputOption='RAW', body={'values':data}).execute()
print(f"\nWrote {len(df)} tweets to tab {TAB}")
print(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
