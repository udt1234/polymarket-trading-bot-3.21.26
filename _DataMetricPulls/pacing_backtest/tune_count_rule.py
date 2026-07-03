"""Tuning pass: find the (window, reply-rule) combo that reproduces official winners.

For several clean 7-day auctions with known winners, pull a WIDE window once, then
slice/score offline under combinations of:
  WINDOW   : canonical (auction start/end)   vs   noonET (12:00 ET -> 12:00 ET from slug dates)
  REPLYRULE: none | self(in_reply==Elon) | selfthread(conv root authored by Elon) | all
Reposts + quotes + originals always count. Print which combo hits the most winners.
"""
import os, sys, re, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'
ELON_ID = '44196397'
ET = ZoneInfo('America/New_York')
BEARER = next(l.split('=',1)[1].strip() for l in open(ROOT/'.env', encoding='utf-8') if l.startswith('X_BEARER_TOKEN='))
MONTHS = {m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

# ---- pick validated weeks (clean 7-day, proper window, prefer high-conf) ----
auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True); auc['end_utc']=pd.to_datetime(auc['end_utc'],utc=True)
c = auc[(auc.duration_type=='7-day') & (auc.winning_bucket!='')
        & (~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))
        & (auc.start_utc>=pd.Timestamp('2025-09-05',tz='UTC'))].copy()
c['days']=(c.end_utc-c.start_utc).dt.total_seconds()/86400
c=c[(c.days>=6.5)&(c.days<=7.6)].sort_values('start_utc')
c=c.reset_index(drop=True)
step=max(1,len(c)//7)
picks=c.iloc[::step].head(7)
if 'elon-musk-of-tweets-may-22-may-29' not in picks.auction_slug.values:
    picks=pd.concat([picks, c[c.auction_slug=='elon-musk-of-tweets-may-22-may-29']])
picks=picks.drop_duplicates('auction_slug')
print("weeks under test:")
print(picks[['auction_slug','start_utc','confidence','winning_bucket']].to_string(index=False))

def parse_noonET(slug, ref_year):
    s = slug.replace('elon-musk-of-tweets-','')
    toks = s.split('-')
    mo1 = MONTHS.get(toks[0].lower()); d1 = int(toks[1])
    if len(toks)>=4 and toks[2].lower() in MONTHS:
        mo2 = MONTHS[toks[2].lower()]; d2 = int(toks[3])
    else:
        mo2 = mo1; d2 = int(toks[2])
    y1=ref_year; y2=ref_year+ (1 if mo2<mo1 else 0)
    st = datetime(y1,mo1,d1,12,0,tzinfo=ET); en = datetime(y2,mo2,d2,12,0,tzinfo=ET)
    return pd.Timestamp(st).tz_convert('UTC'), pd.Timestamp(en).tz_convert('UTC')

def pull(start_utc, end_utc):
    rows, token, pages = [], None, 0
    while True:
        p={'query':f'from:{ELON_ID}','start_time':start_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
           'end_time':end_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),'max_results':'500',
           'tweet.fields':'created_at,referenced_tweets,in_reply_to_user_id,conversation_id'}
        if token: p['next_token']=token
        url='https://api.x.com/2/tweets/search/all?'+urllib.parse.urlencode(p)
        req=urllib.request.Request(url, headers={'Authorization':f'Bearer {BEARER}'})
        try:
            with urllib.request.urlopen(req) as r: body=json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(8); continue
            print("ERR",e.code,e.read().decode()[:200]); raise
        rows+=body.get('data',[]); token=body.get('meta',{}).get('next_token'); pages+=1
        if not token or pages>=40: break
        time.sleep(1.1)
    return rows

def lookup_authors(ids):
    out={}
    ids=list({str(i) for i in ids})
    for i in range(0,len(ids),100):
        chunk=ids[i:i+100]
        url='https://api.x.com/2/tweets?'+urllib.parse.urlencode({'ids':','.join(chunk),'tweet.fields':'author_id'})
        req=urllib.request.Request(url, headers={'Authorization':f'Bearer {BEARER}'})
        try:
            with urllib.request.urlopen(req) as r: body=json.loads(r.read())
            for t in body.get('data',[]): out[t['id']]=t.get('author_id')
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(8);
            else: pass
        time.sleep(1.1)
    return out

def snow_ms(tid): return (int(tid)>>22)+1288834974657
def typ(t):
    refs=[r['type'] for r in t.get('referenced_tweets',[])]
    if 'retweeted' in refs: return 'repost'
    if 'quoted' in refs: return 'quote'
    if 'replied_to' in refs: return 'reply'
    return 'original'
def parse_bucket(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),None)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def in_bucket(n,lbl):
    rg=parse_bucket(lbl)
    return rg and rg[0]<=n<=(rg[1] if rg[1] is not None else 1e12)

RULES=['none','self','selfthread','all']
WINS=['canonical','noonET']
grid={(w,r):0 for w in WINS for r in RULES}
detail=[]
for _,a in picks.iterrows():
    slug=a['auction_slug']; winner=a['winning_bucket']
    n_st,n_en=parse_noonET(slug, a['start_utc'].year)
    wide_s=min(n_st,a['start_utc'])-timedelta(hours=12); wide_e=max(n_en,a['end_utc'])+timedelta(hours=12)
    rows=pull(wide_s,wide_e)
    # conv authors for replies
    conv_ids={t.get('conversation_id') for t in rows if typ(t)=='reply'}
    conv_auth=lookup_authors(conv_ids) if conv_ids else {}
    recs=[]
    for t in rows:
        ty=typ(t)
        recs.append({'ms':snow_ms(t['id']),'ty':ty,'irt':str(t.get('in_reply_to_user_id')),
                     'conv':str(t.get('conversation_id')),
                     'cauth':conv_auth.get(str(t.get('conversation_id')))})
    df=pd.DataFrame(recs)
    print(f"\n{slug}  winner={winner}  pulled={len(df)}  canon={a['start_utc']}->{a['end_utc']}  noonET={n_st}->{n_en}")
    for w in WINS:
        ws,we=(a['start_utc'],a['end_utc']) if w=='canonical' else (n_st,n_en)
        wm0,wm1=int(ws.timestamp()*1000),int(we.timestamp()*1000)
        win=df[(df.ms>=wm0)&(df.ms<wm1)]
        base=int(win.ty.isin(['original','quote','repost']).sum())
        rep=win[win.ty=='reply']
        for r in RULES:
            if r=='none': add=0
            elif r=='self': add=int((rep.irt==ELON_ID).sum())
            elif r=='selfthread': add=int((rep.cauth==ELON_ID).sum())
            else: add=len(rep)
            cnt=base+add; hit=in_bucket(cnt,winner)
            if hit: grid[(w,r)]+=1
            detail.append((slug,winner,w,r,cnt,'HIT' if hit else ''))

print("\n================ COMBO SCOREBOARD (weeks hit / total) ================")
tot=len(picks)
for w in WINS:
    for r in RULES:
        print(f"  window={w:9} reply={r:11} -> {grid[(w,r)]}/{tot} winners reproduced")
print("\n================ detail ================")
print(f"{'slug':42} {'winner':9} {'window':9} {'rule':11} {'count':>5} hit")
for slug,winner,w,r,cnt,hit in detail:
    print(f"{slug[:42]:42} {winner:9} {w:9} {r:11} {cnt:>5} {hit}")
