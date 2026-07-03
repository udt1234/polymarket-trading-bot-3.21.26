"""Head-to-head: the NEW Reverse-pace + Kalman edge (fair-value dip-buy + model band + hold)
vs the bot's 3 existing styles, on the same Elon auctions, same fills, same costs:
  hold_fav      = buy the market FAVORITE mid-auction, hold to resolution  ('hold till the end')
  scrape_sell   = seesaw the in-play bracket (buy dip / sell pop), exit before the end ('scrape & sell')
  scrape_hold   = BLIND dip-buy the in-play brackets, hold to resolution   ('scrape & hold')
  kalman_edge   = dip-buy only where price < OUR fair value, in the model's band, hold  (NEW)
P&L per position (1 unit each), uniform per-side cost. Walk-forward Kalman priors. BACKTEST_RULES."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON=ROOT/'_DataMetricPulls'/'canonical'; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms')
pt=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pt.min()),int(pt.max())
def obs(s,e): return int(np.searchsorted(pt,e)-np.searchsorted(pt,s))
prc=pd.read_parquet(OUT/'clob_prices.parquet'); pidx={}
for (sl,bk),g in prc.sort_values('t').groupby(['auction_slug','bucket']): pidx[(sl,bk)]=(g['t'].to_numpy(),g['price'].to_numpy())
buckets_by=prc.groupby('auction_slug')['bucket'].apply(lambda s:sorted(set(s.dropna()))).to_dict()
def price_at(sl,bk,t):
    a=pidx.get((sl,bk))
    if a is None: return None
    ts,ps=a; i=np.searchsorted(ts,t,side='right')-1
    if i<0: return None
    v=float(ps[i]); return v if 0<v<1 else None
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
    except: return None
    y2=yr+(1 if mo2<mo1 else 0)
    return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
cand=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(auc.confidence.isin(['high','medium']))&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
sel=[]
for _,a in cand.iterrows():
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w; dur=a.duration_type; days=(e-s)/86400
    if dur=='7-day' and not 6.5<=days<=7.6: continue
    if dur=='2-day' and not 1.5<=days<=2.6: continue
    if e>c1 or s<c0+7200: continue
    br=[(b,pbk(b)) for b in buckets_by.get(a.auction_slug,[]) if (a.auction_slug,b) in pidx and pbk(b)]
    if len(br)<3 or obs(s,e)<=0: continue
    sel.append(dict(slug=a.auction_slug,dur=dur,s=s,e=e,br=br,winner=str(a.winning_bucket)))
sel=sorted(sel,key=lambda x:x['s'])
def krate(o,eh,rates):
    if not rates: return o/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(o/max(eh,1)-x)
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(lo,hi,proj,sig):
    zl=(lo-0.5-proj)/sig
    return max(1e-9,(1-ncdf(zl)) if hi>=10**8 else (ncdf((hi+0.5-proj)/sig)-ncdf(zl)))

def frame(a,priors):
    s,e,br=a['s'],a['e'],a['br']; total=(e-s)/3600
    F=[]
    for hh in range(max(2,int(0.05*total)), max(3,int(0.97*total))):
        t=s+hh*3600; o=obs(s,t); rh=total-hh
        if rh<=0.5: continue
        proj=o+krate(o,hh,priors)*rh; sig=math.sqrt(max(proj-o,1))*1.5+4
        prices={}; probs={}
        for b,(lo,hi) in br:
            p=price_at(a['slug'],b,t); prices[b]=p; probs[b]=bprob(lo,hi,proj,sig)
        ps=sum(probs.values()) or 1; probs={b:v/ps for b,v in probs.items()}
        F.append(dict(hh=hh,ef=hh/total,proj=proj,prices=prices,probs=probs))
    return F

COSTS=[0.01,0.02]
for COST in COSTS:
    book={s:[] for s in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']}
    for a in sel:
        winner=a['winner']
        priors=[p['actual'] if False else obs(p['s'],p['e'])/((p['e']-p['s'])/3600) for p in sel if p['e']<a['s'] and p['e']>p['s']]
        if not priors: continue
        F=frame(a,priors)
        if len(F)<6: continue
        pricedb=[b for b,_ in a['br']]
        # ---- hold_fav: buy market favorite ~50% elapsed, hold ----
        mid=min(F,key=lambda r:abs(r['ef']-0.5))
        pf={b:v for b,v in mid['prices'].items() if v}
        if pf:
            fav=max(pf,key=pf.get); bp=pf[fav]
            book['hold_fav'].append((1.0 if fav==winner else 0.0)-bp-COST)
        # ---- scrape_sell: seesaw the in-play bracket, exit before end ----
        inplay=None; best=1
        for b in pricedb:
            ser=[r['prices'].get(b) for r in F if r['prices'].get(b)]
            if len(ser)<6: continue
            d=abs(np.median(ser)-0.5)
            if d<best: best=d; inplay=b
        if inplay:
            ser=[(r['ef'],r['prices'].get(inplay)) for r in F if r['prices'].get(inplay)]
            ps=np.array([x[1] for x in ser]); ema=pd.Series(ps).ewm(span=6,adjust=False).mean().to_numpy()
            pos=None
            for i in range(len(ps)):
                p=ps[i]
                if pos is None and 0.15<p<0.75 and p<ema[i]-0.04: pos=p
                elif pos is not None and (p>=ema[i]+0.04 or p<=pos-0.06):
                    book['scrape_sell'].append(p-pos-2*COST); pos=None
            if pos is not None: book['scrape_sell'].append(ps[-1]-pos-2*COST)
        # ---- scrape_hold: BLIND dip-buy in-play brackets, hold ----
        for b in pricedb:
            ser=[r['prices'].get(b) for r in F if r['prices'].get(b)]
            if len(ser)<6 or not (0.08<np.median([x for x in ser if x])<0.85): continue
            arr=np.array(ser); rollmin=pd.Series(arr).rolling(6,min_periods=3).min().to_numpy()
            for i in range(3,len(arr)):
                if arr[i]<rollmin[i-1]-0.005 and arr[i]>0.02:
                    book['scrape_hold'].append((1.0 if b==winner else 0.0)-arr[i]-COST); break
        # ---- kalman_edge: dip vs OUR fair value, model band only, hold ----
        band=[b for b,_ in a['br'] if mid['probs'].get(b,0)>=0.08]
        for b in band:
            bought=False
            for r in F:
                p=r['prices'].get(b); fair=r['probs'].get(b,0)
                if p and fair>0.05 and p<fair-0.03 and p>0.02:
                    book['kalman_edge'].append((1.0 if b==winner else 0.0)-p-COST); bought=True; break
    print(f"\n================  per-side cost = {COST*100:.0f}c  ================")
    print(f"{'strategy':<14}{'positions':>10}{'total P&L':>11}{'avg/pos':>10}{'win%':>7}{'ROI':>8}")
    for st in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']:
        v=np.array(book[st])
        if not len(v): print(f"{st:<14}{'0':>10}"); continue
        tot=v.sum(); avg=v.mean(); win=100*np.mean(v>0)
        cost_basis=len(v)  # ~1 unit deployed per position
        print(f"{st:<14}{len(v):>10}{tot*100:>10.0f}c{avg*100:>9.2f}c{win:>6.0f}%{100*tot/max(1,cost_basis):>7.1f}%")
    print("  (avg/pos = mean cents made per 1-share position; kalman_edge is the NEW reverse-pace+Kalman)")
