# -*- coding: utf-8 -*-
"""TRUE average performance: run single_auction_seesaw (calibrated sigma, per-tweet cap, no MAXINV cap)
on every pmxt 2-day auction, BASE vs pace+edge OVERLAY. EXCLUDE any auction whose coverage guard flags
the WINNER's price data as missing. Report per-auction + pooled."""
import subprocess, sys, os, re, glob
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; ET=ZoneInfo('America/New_York'); HERE=os.path.dirname(os.path.abspath(__file__)); OUT=HERE+"/audit_out3"
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed]; c1=int(bf.ms.max()//1000)
M={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-'); mo1=M[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in M: mo2=M[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
PMS=int(pd.Timestamp(datetime(2026,4,15,tzinfo=ET)).timestamp()); PME=int(pd.Timestamp(datetime(2026,6,22,tzinfo=ET)).timestamp())
slugs=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium') or str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    try: s,e=noon(a.auction_slug)
    except: continue
    if not 1.5<=(e-s)/86400<=2.6 or s<PMS or e>min(PME,c1): continue
    tok=a.bracket_yes_token_ids
    if not tok: continue
    slugs.append(a.auction_slug)
slugs=sorted(set(slugs))
def run(slug,react):
    env=dict(os.environ,AUCTION=slug)
    if react: env['REACT6H']='1'; env['PACE_EDGE']='1'
    p=subprocess.run([sys.executable,'-u',HERE+'/single_auction_seesaw.py'],capture_output=True,text=True,env=env,timeout=600)
    o=p.stdout; pl=re.search(r'TOTAL P&L \$([+-]?[\d.]+)',o); tr=re.search(r'TOTAL TRADES: (\d+)',o)
    w=re.search(r'WINNER (\S+) \| actual count (\d+)',o)
    wm='INCLUDES THE WINNER' in o
    return {'pnl':float(pl.group(1)) if pl else float('nan'),'trades':int(tr.group(1)) if tr else 0,
            'winner':w.group(1) if w else '?','actual':int(w.group(2)) if w else 0,'winner_missing':wm}
rows=[]
for slug in slugs:
    b=run(slug,False)
    if b['winner_missing'] or b['pnl']!=b['pnl']:
        print(f"  SKIP {slug.replace('elon-musk-of-tweets-',''):<24} (winner data missing / no run)",flush=True); continue
    ov=run(slug,True)
    rows.append({'auction':slug.replace('elon-musk-of-tweets-',''),'winner':b['winner'],'actual':b['actual'],
                 'BASE_pnl':round(b['pnl']),'OVERLAY_pnl':round(ov['pnl']),'BASE_tr':b['trades']})
    print(f"  ok {slug.replace('elon-musk-of-tweets-',''):<24} win {b['winner']:<7} act {b['actual']:>3} | BASE ${b['pnl']:+.0f} | OVERLAY ${ov['pnl']:+.0f}",flush=True)
df=pd.DataFrame(rows); df.to_csv(OUT+"/clean_sweep.csv",index=False)
print("\n=== CLEAN SWEEP (fully-covered auctions only, calibrated sigma) ===")
print(df.to_string(index=False))
for col in ['BASE_pnl','OVERLAY_pnl']:
    v=df[col]
    print(f"\n{col}: pooled ${v.sum():+,.0f} | per-auction mean ${v.mean():+.0f} median ${v.median():+.0f} | win-rate {100*(v>0).mean():.0f}% | best ${v.max():+.0f} worst ${v.min():+.0f}")
print(f"\nauctions used: {len(df)}  (excluded winner-missing)")
