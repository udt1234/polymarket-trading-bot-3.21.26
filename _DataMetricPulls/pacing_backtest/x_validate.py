import os, sys, json, urllib.request, urllib.parse
sys.stdout.reconfigure(encoding='utf-8')

# load bearer from .env (never print it)
ENV = r"C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\.env"
bearer = None
for line in open(ENV, encoding='utf-8'):
    if line.startswith('X_BEARER_TOKEN='):
        bearer = line.split('=', 1)[1].strip()
assert bearer, "no X_BEARER_TOKEN in .env"

params = {
    'query': 'from:elonmusk',
    'start_time': '2026-05-20T00:00:00Z',
    'end_time': '2026-05-20T06:00:00Z',
    'max_results': '10',
    'tweet.fields': 'created_at,author_id,referenced_tweets,in_reply_to_user_id,conversation_id,note_tweet,public_metrics,edit_history_tweet_ids,lang',
    'expansions': 'referenced_tweets.id,referenced_tweets.id.author_id,in_reply_to_user_id',
}
url = 'https://api.x.com/2/tweets/search/all?' + urllib.parse.urlencode(params)
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {bearer}'})
try:
    with urllib.request.urlopen(req) as r:
        body = json.loads(r.read())
        print("HTTP", r.status)
except urllib.error.HTTPError as e:
    print("HTTP ERROR", e.code)
    print(e.read().decode()[:1500])
    sys.exit()

data = body.get('data', [])
print(f"returned {len(data)} tweets")
print(f"meta: {body.get('meta')}")

def snowflake_ms(tid):
    return (int(tid) >> 22) + 1288834974657

for t in data[:6]:
    ms = snowflake_ms(t['id'])
    refs = t.get('referenced_tweets', [])
    rtypes = [r['type'] for r in refs] if refs else []
    in_reply = t.get('in_reply_to_user_id')
    print(f"\nid={t['id']} ms={ms} created_at={t.get('created_at')}")
    print(f"   refs={rtypes} in_reply_to={in_reply} conv={t.get('conversation_id')}")
    print(f"   text={ (t.get('text') or '')[:80]!r }")
