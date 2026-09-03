# -*- coding: utf-8 -*-
"""Run the 16 fully-covered clean auctions with LAST_H=12 (only trade in the last 12h) and compare
per-auction + pooled P&L to the FULL run (clean_sweep.csv BASE_pnl). Answers: does gating entries to
the last 12 hours -- where the locked pace's bias is ~0 -- kill the early-overshoot wrong-bracket losses?"""
import subprocess, sys, os, re
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
HERE=os.path.dirname(os.path.abspath(__file__)); OUT=HERE+"/audit_out3"
au=pd.read_csv(OUT+"/clean_sweep.csv")
def run(slug,last_h):
    env=dict(os.environ,AUCTION=slug,LAST_H=str(last_h)); env.pop('REACT6H',None); env.pop('PACE_EDGE',None)
    p=subprocess.run([sys.executable,'-u',HERE+'/single_auction_seesaw.py'],capture_output=True,text=True,env=env,timeout=600)
    o=p.stdout; pl=re.search(r'TOTAL P&L \$([+-]?[\d.]+)',o); tr=re.search(r'TOTAL TRADES: (\d+)',o)
    return (float(pl.group(1)) if pl else float('nan'), int(tr.group(1)) if tr else 0)
rows=[]
for _,a in au.iterrows():
    slug='elon-musk-of-tweets-'+a.auction
    pnl12,tr12=run(slug,12)
    rows.append({'auction':a.auction,'winner':a.winner,'actual':a.actual,'FULL_pnl':round(a.BASE_pnl),'LAST12_pnl':round(pnl12),'LAST12_trades':tr12})
    print(f"  {a.auction:<22} win {str(a.winner):<7} | FULL ${a.BASE_pnl:+.0f} -> LAST12 ${pnl12:+.0f}  ({tr12} trades)",flush=True)
df=pd.DataFrame(rows); df.to_csv(OUT+"/last12_compare.csv",index=False)
print("\n=== LAST-12H-ONLY vs FULL (16 clean auctions) ===")
print(df.to_string(index=False))
for col in ['FULL_pnl','LAST12_pnl']:
    v=df[col]; print(f"\n{col:>11}: pooled ${v.sum():+,.0f} | mean ${v.mean():+.0f} | median ${v.median():+.0f} | win-rate {100*(v>0).mean():.0f}% | best ${v.max():+.0f} worst ${v.min():+.0f}")
print(f"\nLAST12 total trades: {df.LAST12_trades.sum()}")
