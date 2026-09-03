# -*- coding: utf-8 -*-
"""ARB RE-TEST, done properly. My earlier test was TAKER-only (sum of best ASKS) and I declared arb
dead. The bot is MAKER-only. For a binary bracket, YES and NO are separate books:
  TAKER pair cost = YES_ask + NO_ask  ~= 1 + spread   (always loses)
  MAKER pair cost = YES_bid + NO_bid  ~= 1 - spread   (RISKLESS if both fill: YES+NO always pays $1)
Measures on every 2-day auction with real L2."""
import duckdb, sys, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
def q(x): return con.execute(x).df()
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
L2START=int(datetime(2026,4,13,19,tzinfo=timezone.utc).timestamp()); NOWC=int(datetime(2026,6,23,tzinfo=timezone.utc).timestamp())
rows=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w
    if not(1.5<=(e-s)/86400<=2.6) or e<L2START or e>NOWC: continue
    try:
        Y=json.loads(a.bracket_yes_token_ids); N=json.loads(a.bracket_no_token_ids)
    except: continue
    tok={}
    for lbl,t in Y.items():
        if isinstance(t,str) and t.isdigit() and pbk(lbl): tok[str(t)]=(lbl,'Y')
    for lbl,t in N.items():
        if isinstance(t,str) and t.isdigit() and pbk(lbl): tok[str(t)]=(lbl,'N')
    files=l2files(s,e)
    if len(files)<20 or len(tok)<6: continue
    arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in tok)+")"
    px=q(f"""SELECT asset_id,(ts//600000)*600000 bar, arg_max(best_bid,ts) bid, arg_max(best_ask,ts) ask
        FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change'
        AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} GROUP BY 1,2""")
    if px.empty: continue
    px['lbl']=px.asset_id.map(lambda t: tok[str(t)][0]); px['side']=px.asset_id.map(lambda t: tok[str(t)][1])
    yb=px[px.side=='Y'].pivot_table(index='bar',columns='lbl',values='bid',aggfunc='last').sort_index().ffill()
    ya=px[px.side=='Y'].pivot_table(index='bar',columns='lbl',values='ask',aggfunc='last').sort_index().ffill()
    nb=px[px.side=='N'].pivot_table(index='bar',columns='lbl',values='bid',aggfunc='last').sort_index().ffill()
    na=px[px.side=='N'].pivot_table(index='bar',columns='lbl',values='ask',aggfunc='last').sort_index().ffill()
    common=sorted(set(yb.columns)&set(nb.columns)); bars=sorted(set(yb.index)&set(nb.index))
    if not common or len(bars)<20: continue
    yb,ya,nb,na=[d.reindex(index=bars,columns=common) for d in (yb,ya,nb,na)]
    setask=ya.sum(axis=1,skipna=True)
    taker=(ya+na).stack().dropna(); maker=(yb+nb).stack().dropna()
    def suffix_min(d): return d[::-1].cummin()[::-1].shift(-1)
    yfill=(suffix_min(ya)<=yb); nfill=(suffix_min(na)<=nb); both=(yfill&nfill)
    cost=(yb+nb); lockvals=(1.0-cost)[both].stack().dropna()
    rows.append({'slug':a.auction_slug.replace('elon-musk-of-tweets-',''),'bars':len(bars),'brackets':len(common),
        'setask_med':float(setask.median()),'setask_pct_below1':100*float((setask<1.0).mean()),
        'taker_pair_med':float(taker.median()),'taker_pair_pct_below1':100*float((taker<1.0).mean()),
        'maker_pair_med':float(maker.median()),'maker_pair_pct_below1':100*float((maker<1.0).mean()),
        'both_fill_rate%':100*float(both.stack().mean()) if both.size else np.nan,
        'locked_margin_med':float(lockvals.median()) if len(lockvals) else np.nan})
r=pd.DataFrame(rows)
pd.set_option('display.width',250)
print(f"=== ARB RE-TEST: MAKER vs TAKER  (n={len(r)} two-day auctions, real L2, YES+NO books) ===\n")
print(r.round(3).to_string(index=False))
print("\n"+"="*104)
print(f"1. COMPLETE-SET TAKER (sum of YES asks)  median ${r.setask_med.median():.3f}  below $1 on {r.setask_pct_below1.median():.2f}% of bars  -> DEAD (my old test)")
print(f"2. COMPLEMENT TAKER  (YES_ask+NO_ask)    median ${r.taker_pair_med.median():.3f}  below $1 on {r.taker_pair_pct_below1.median():.2f}% of bars  -> DEAD (you pay the spread)")
print(f"3. COMPLEMENT MAKER  (YES_bid+NO_bid)    median ${r.maker_pair_med.median():.3f}  below $1 on {r.maker_pair_pct_below1.median():.2f}% of bars  -> THE ARB")
print(f"   median RISKLESS margin per matched pair: {100*(1-r.maker_pair_med.median()):.1f} cents")
print(f"4. BOTH LEGS FILL (a later ask crosses to each resting bid): {r['both_fill_rate%'].median():.1f}% of quote-bars")
print(f"   median locked margin on pairs that DID complete: {100*r.locked_margin_med.median():.1f} cents")
print("="*104)
r.to_csv(f"{OUT}/arb_maker_retest.csv",index=False)
print(f"\nWROTE {OUT}/arb_maker_retest.csv")
