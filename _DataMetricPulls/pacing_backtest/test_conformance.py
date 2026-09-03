# -*- coding: utf-8 -*-
"""Conformance tests for backtest_books.py. Reads audit_out2/trades.csv + canonical and asserts each
strategy obeyed its rule (R1-R6, R8-partial). If ANY test fails, the P&L is NOT to be trusted.
R7 (no look-ahead) is verified by the adversarial code audit, not here."""
import sys, glob, json; sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
MARGIN=0.03; BAND_FLOOR=0.05; HAIRCUT=0.01; EPS=1e-6
tr=pd.read_csv(f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out2/trades.csv")
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{ROOT}/_DataMetricPulls/canonical/auctions/elonmusk/*.parquet"))],ignore_index=True)
wmap={r.auction_slug:str(r.winning_bucket).strip() for _,r in auc.iterrows()
      if str(r.confidence) in ('high','medium') and str(r.resolution_status) in ('resolved_yes','resolved_yes_gamma')}

results=[]
def check(name, ok, detail):
    results.append((name, bool(ok), detail))

buys=tr[tr.side=='BUY']; sells=tr[tr.side=='SELL']
# R1 winners are the official canonical Gamma winners (not self-count)
badw=[s for s in tr.slug.unique() if s in wmap and (tr[tr.slug==s].winner.iloc[0]!=wmap[s])]
check("R1 winner == canonical official Gamma winner", len(badw)==0, f"{len(badw)} slugs mismatch; every backtested slug uses its high/med-confidence Gamma winning_bucket")
# R2 every BUY is a maker fill: fill_price <= that hour's ask (we rested at the bid, never lifted the ask)
r2=(buys.fill_price<=buys.ask+EPS).all()
check("R2 maker BUY (fill_price <= ask)", r2, f"{(buys.fill_price>buys.ask+EPS).sum()} buys filled above ask (would be taking)")
# R3 S2 never sells
n_s2_sell=len(tr[(tr.book=='S2')&(tr.side=='SELL')])
check("R3 S2 never sells", n_s2_sell==0, f"S2 SELL orders = {n_s2_sell} (must be 0; S2 holds to resolution)")
# R4 S2 buys are BAND (fair>=BAND_FLOOR) AND below fair by >= MARGIN
s2b=tr[(tr.book=='S2')&(tr.side=='BUY')]
r4a=(s2b.fair>=BAND_FLOOR-EPS).all(); r4b=((s2b.fair-s2b.fill_price)>=MARGIN-EPS).all()
check("R4 S2 buys band-only + below fair", r4a and r4b,
      f"band-floor viol={ (s2b.fair<BAND_FLOOR-EPS).sum() }, below-fair viol={ ((s2b.fair-s2b.fill_price)<MARGIN-EPS).sum() }")
# R5 S1 enters below fair; S1 'exit above fair' sells require hi_bid >= fair+MARGIN
s1b=tr[(tr.book=='S1')&(tr.side=='BUY')]
r5a=((s1b.fair-s1b.fill_price)>=MARGIN-EPS).all()
s1x=tr[(tr.book=='S1')&(tr.side=='SELL')&(tr.rule.str.contains('exit above fair',na=False))]
r5b=((s1x.hi_bid>=s1x.fair+MARGIN-EPS).all()) if len(s1x) else True
check("R5 S1 enters below fair, exits above fair", r5a and r5b,
      f"entry viol={((s1b.fair-s1b.fill_price)<MARGIN-EPS).sum()}, exit viol={ (s1x.hi_bid<s1x.fair+MARGIN-EPS).sum() if len(s1x) else 0 }")
# R6 S3 never sells a CORE (held) lot: no S3 SELL carries the 'held' rule
s3sell=tr[(tr.book=='S3')&(tr.side=='SELL')]
r6=(~s3sell.rule.str.contains('held',na=False)).all() if len(s3sell) else True
check("R6 S3 core never sold (all S3 sells are sleeve)", r6, f"{ s3sell.rule.str.contains('held',na=False).sum() } S3 core-lot sells found")
# R8 conservative haircut: every 'exit above fair' sold at fair+MARGIN-HAIRCUT (haircut applied)
xa=tr[tr.rule.str.contains('exit above fair',na=False)]
r8=(abs(xa.fill_price-(xa.fair+MARGIN-HAIRCUT))<=EPS).all() if len(xa) else True
check("R8 conservative haircut on scalp exits", r8, f"{ (abs(xa.fill_price-(xa.fair+MARGIN-HAIRCUT))>EPS).sum() if len(xa) else 0 } exits missing the haircut")

print("="*72); print("CONFORMANCE TESTS  (backtest_books.py)"); print("="*72)
allok=True
for name,ok,detail in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok: print(f"         -> {detail}"); allok=False
    elif detail and 'viol' in detail: pass
print("="*72)
print("ALL CONFORMANCE TESTS PASSED" if allok else "SOME TESTS FAILED -> P&L NOT TRUSTWORTHY")
print(f"orders: {len(tr)} | buys {len(buys)} sells {len(sells)} | books {sorted(tr.book.unique())}")
sys.exit(0 if allok else 1)
