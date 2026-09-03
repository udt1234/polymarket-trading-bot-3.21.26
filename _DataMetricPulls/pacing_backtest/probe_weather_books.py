# -*- coding: utf-8 -*-
"""LIVE book-depth probe on the top weather reward targets. Fetches temperature markets fresh from Gamma
(full slug + clobTokenIds + reward config), pulls the live CLOB order book, measures competing maker
NOTIONAL inside the reward band around mid, and computes our REAL share at a $5k quote + the true spread."""
import urllib.request, json, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def get(u):
    req=urllib.request.Request(u, headers={'User-Agent':'Mozilla/5.0'})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())
# fetch open reward markets, keep temperature ones with a live rate + tokens
mk=[]; off=0; seen=set()
for _ in range(20):
    try: data=get(f'https://gamma-api.polymarket.com/markets?closed=false&active=true&enableOrderBook=true&limit=100&offset={off}&order=volume24hr&ascending=false')
    except Exception: break
    if not data: break
    for m in data:
        q=str(m.get('question','')).lower(); cid=m.get('conditionId')
        if 'temperature' not in q or cid in seen: continue
        seen.add(cid)
        cr=m.get('clobRewards') or []; rate=max([float(r.get('rewardsDailyRate') or 0) for r in cr]+[0])
        toks=m.get('clobTokenIds'); toks=json.loads(toks) if isinstance(toks,str) else toks
        if rate<=0 or not toks: continue
        mk.append({'q':m.get('question',''),'tok':toks[0],'rate':rate,'v':float(m.get('rewardsMaxSpread') or 4.5),'liq':float(m.get('liquidity') or 0)})
    off+=100; time.sleep(0.1)
mk=sorted(mk,key=lambda x:-x['rate'])[:10]
CAP=5000.0
print(f"probed {len(mk)} temperature markets")
print(f"{'market':<46}{'rate':>5}{'spread':>7}{'inband$':>9}{'ourShr':>7}{'toUs':>7}")
tot=0.0; ok=0
for m in mk:
    try: bk=get(f"https://clob.polymarket.com/book?token_id={m['tok']}")
    except Exception as ex:
        print(f"{str(m['q'])[:46]:<46}  book ERR {str(ex)[:30]}"); continue
    bids=[(float(b['price']),float(b['size'])) for b in bk.get('bids',[])]
    asks=[(float(a['price']),float(a['size'])) for a in bk.get('asks',[])]
    if not bids or not asks: print(f"{str(m['q'])[:46]:<46}  empty/one-sided book"); continue
    bb=max(p for p,_ in bids); ba=min(p for p,_ in asks); mid=(bb+ba)/2; spread=ba-bb; band=m['v']/100.0
    comp=sum(p*s for p,s in bids if p>=mid-band)+sum(p*s for p,s in asks if p<=mid+band)
    share=CAP/(CAP+comp) if comp>0 else 1.0; to_us=m['rate']*share; tot+=to_us; ok+=1
    print(f"{str(m['q'])[:46]:<46}{m['rate']:>5.0f}{spread*100:>6.1f}c{comp:>9.0f}{share:>6.0%}{to_us:>7.0f}")
    time.sleep(0.15)
print(f"\nREAL in-band basket ({ok} weather mkts, live books): est ${tot:.0f}/day to us at $5k each (PRE adverse-selection)")
