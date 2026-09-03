# -*- coding: utf-8 -*-
"""Pick the top late-blast auctions (most tweets in the last 6h) that have pmxt price data, then run
BASE vs the tuned REACT6H overlay on each and report the P&L delta + overlay activity."""
import subprocess, sys, os, re, glob, json
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; ET=ZoneInfo('America/New_York')
HERE=os.path.dirname(os.path.abspath(__file__)); OUT=HERE+"/audit_out3"
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms'); ms=bf.ms.to_numpy().astype('int64'); c1=int(ms.max()//1000)
M={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
def noon(sl):
    tk=str(sl).replace('elon-musk-of-tweets-','').split('-'); mo1=M[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in M: mo2=M[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
PMX_START=int(pd.Timestamp(datetime(2026,4,15,0,tzinfo=ET)).timestamp())    # pmxt price data starts ~Apr 13
PMX_END=int(pd.Timestamp(datetime(2026,6,22,0,tzinfo=ET)).timestamp())      # pmxt price data ends ~Jun 22
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
cand=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    try: s,e=noon(a.auction_slug)
    except: continue
    if not 1.5<=(e-s)/86400<=2.6 or s<PMX_START or e>PMX_END or e>c1: continue
    tok=a.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    if not tok: continue
    last6=int(np.searchsorted(ms,e*1000)-np.searchsorted(ms,(e-6*3600)*1000))
    cand.append((a.auction_slug,str(a.winning_bucket),last6))
cand=sorted(cand,key=lambda x:-x[2])
picks=cand[:4]
print("pmxt-covered late-blast auctions (top by last-6h tweets):")
for sl,win,l6 in cand[:8]: print(f"  {sl.replace('elon-musk-of-tweets-',''):<26} winner {win:<8} last6h_tweets {l6}")
print(f"\nrunning BASE vs OVERLAY on: {[p[0].replace('elon-musk-of-tweets-','') for p in picks]}\n")
def run(slug,react,pace_edge=True):
    env=dict(os.environ,AUCTION=slug)
    if react: env['REACT6H']='1'; env['PACE_EDGE']='1' if pace_edge else '0'
    p=subprocess.run([sys.executable,'-u',HERE+'/single_auction_seesaw.py'],capture_output=True,text=True,env=env,timeout=600)
    o=p.stdout; tr=re.search(r'TOTAL TRADES: (\d+)',o); pl=re.search(r'TOTAL P&L \$([+-]?[\d.]+)',o)
    if not pl:
        err=[x for x in p.stderr.strip().splitlines() if x.strip()]
        print(f"   RUN FAIL {slug.replace('elon-musk-of-tweets-','')}: {err[-1] if err else 'no output'}")
    return (int(tr.group(1)) if tr else 0, float(pl.group(1)) if pl else float('nan'))
def ovcount(path):
    try:
        rc=pd.read_csv(path); return rc[rc.action.isin(['SELL-EARLY','BUY-HOLD-PACE'])].action.value_counts().to_dict()
    except Exception: return {}
rows=[]
for slug,win,l6 in picks:
    a=slug.replace('elon-musk-of-tweets-','')
    bt,bp=run(slug,False)
    et,ep=run(slug,True,True); fe=ovcount(OUT+"/one_auction_trades_react.csv")
    nt,np_=run(slug,True,False); fn=ovcount(OUT+"/one_auction_trades_react.csv")
    rows.append({'auction':a,'winner':win,'last6h_tw':l6,'BASE':round(bp),'PACE+edge':round(ep),'PACE_noedge':round(np_),
                 'edge_fired':fe,'noedge_fired':fn})
    print(f"  done {a:<24} BASE ${bp:+.0f} | pace+edge ${ep:+.0f} {fe} | pace-noedge ${np_:+.0f} {fn}")
df=pd.DataFrame(rows); df.to_csv(OUT+"/overlay_test.csv",index=False)
print("\n=== REWORKED OVERLAY: sell short on post, buy PACE bracket, rebuy short after 5min ===")
print(df[['auction','winner','last6h_tw','BASE','PACE+edge','PACE_noedge']].to_string(index=False))
print(f"\nTOTALS across {len(df)} markets:  BASE ${df.BASE.sum():+.0f}  |  PACE+edge ${df['PACE+edge'].sum():+.0f}  |  PACE-noedge ${df.PACE_noedge.sum():+.0f}")
print("fire counts (SELL-EARLY / BUY-HOLD-PACE):")
for _,r in df.iterrows(): print(f"  {r.auction:<24} edge:{r.edge_fired}  noedge:{r.noedge_fired}")
