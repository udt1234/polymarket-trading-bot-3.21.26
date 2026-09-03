# -*- coding: utf-8 -*-
"""EVENT-DRIVEN maker complement-pair ARB on the July-6 2-day Elon auction, from OUR RECORDER
(pmxt stops Jun 22; July data is in recordings_pulled). Every price_change tick, in time order.
No bars. For each bracket we rest a YES bid + a NO bid whose sum <= 1-MARGIN; each leg fills when
that side's ask crosses down to our bid; a matched YES+NO pair is riskless $1 at resolution.
Reports overall AND the last hour, where Sir saw the big swings."""
import duckdb, sys, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
REC=f"{ROOT}/_DataMetricPulls/recordings_pulled"; OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MARGIN=0.02; STAKE=200.0
cands=[]
for p in ['elon-tweets-48h.parquet','elon-tweets-48h']:
    fp=os.path.join(REC,p)
    if os.path.isfile(fp): cands=[fp]; break
    if os.path.isdir(fp): cands=sorted(glob.glob(fp+'/*.parquet')); break
if not cands: cands=sorted(glob.glob(f"{REC}/*48h*.parquet"))
if not cands:
    print("NO 2-day recorder data found under recordings_pulled/."); sys.exit()
arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in cands)+"]"
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
def noon(slug):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        return (int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
slugs=con.execute(f"SELECT slug, min(ts) mn, max(ts) mx, count(*) n FROM read_parquet({arr},union_by_name=true) WHERE event_type='price_change' GROUP BY slug ORDER BY mx DESC").df()
slugs['win']=slugs.slug.map(noon)
slugs['win_close']=slugs.win.map(lambda w: datetime.fromtimestamp(w[1],ET).strftime('%m-%d %H:%M') if w else '?')
slugs['recmax']=pd.to_datetime(slugs.mx,unit='ms',utc=True).dt.tz_convert(ET).dt.strftime('%m-%d %H:%M')
print("recent 2-day recorder slugs (window close vs last recorded tick):")
print(slugs.head(8)[['slug','win_close','recmax','n']].to_string(index=False))
# target = the auction that CLOSED July 6 (window end == Jul 6 noon)
JUL6=int(pd.Timestamp(datetime(2026,7,6,12,tzinfo=ET)).timestamp())
target=None
for _,r in slugs.iterrows():
    if r.win and abs(r.win[1]-JUL6)<3600: target=r.slug; break
if target is None:   # fall back to whatever contains july-4-july-6
    for _,r in slugs.iterrows():
        if 'july-4-july-6' in str(r.slug): target=r.slug; break
if target is None:
    print("\nNo auction closing July 6 in the recorder. Pick one from above."); sys.exit()
w=noon(target); s,e=w   # AUCTION WINDOW from the slug (noon ET), not the recording span
row=slugs[slugs.slug==target].iloc[0]
recmax=int(row.mx//1000)
print(f"\nAUCTION: {target} | window {datetime.fromtimestamp(s,ET):%m-%d %H:%M} -> {datetime.fromtimestamp(e,ET):%m-%d %H:%M} ET | last recorded tick {datetime.fromtimestamp(recmax,ET):%m-%d %H:%M}")
if recmax < e-3600: print(f"  WARNING: recording ends {(e-recmax)/3600:.1f}h before the window close - we may be MISSING the actual last hour.")
px=con.execute(f"""SELECT ts, bucket, outcome, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
    WHERE slug='{target}' AND event_type='price_change' AND best_ask IS NOT NULL AND best_bid IS NOT NULL
    AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
px=px[px.outcome.isin(['YES','NO'])].copy()
brks=sorted(px.bucket.dropna().unique()); bimap={b:i for i,b in enumerate(brks)}; nbr=len(brks)
print(f"brackets: {nbr} | outcomes: {sorted(px.outcome.unique())} | usable ticks: {len(px):,}")
tsa=(px.ts.to_numpy()//1000).astype('int64'); bkt=px.bucket.map(bimap).to_numpy(); isyes=(px.outcome.to_numpy()=='YES')
bid=px.best_bid.to_numpy(float); ask=px.best_ask.to_numpy(float); e=int(tsa.max())
yb=np.zeros(nbr); ya=np.full(nbr,1.0); nob=np.zeros(nbr); noa=np.full(nbr,1.0)
active=[None]*nbr; naked_y=[0.0]*nbr; naked_n=[0.0]*nbr; pairs=[]
# CORRECT maker pair arb: commit ONE pair per bracket with py+pn <= 1-MARGIN. Fill each leg only
# when that side's ask crosses down to our committed bid. Once one leg fills, the other may be
# chased UP only to break-even-minus-margin (1-MARGIN-filled_price), so a completed pair ALWAYS
# sums <= 1-MARGIN (margin >= MARGIN). No repricing up, no cross-time mismatches.
for i in range(len(tsa)):
    t=tsa[i]; b=bkt[i]
    if isyes[i]: yb[b]=bid[i]; ya[b]=ask[i]
    else: nob[b]=bid[i]; noa[b]=ask[i]
    a=active[b]
    if a is None:
        if yb[b]>0 and nob[b]>0 and (yb[b]+nob[b])<=1.0-MARGIN:
            active[b]={'py':yb[b],'pn':nob[b],'yfp':None,'nfp':None}
    else:
        yt=(1.0-MARGIN-a['nfp']) if a['nfp'] is not None else a['py']
        nt=(1.0-MARGIN-a['yfp']) if a['yfp'] is not None else a['pn']
        if a['yfp'] is None and ya[b]<=yt+1e-12: a['yfp']=yt
        if a['nfp'] is None and noa[b]<=nt+1e-12: a['nfp']=nt
        if a['yfp'] is not None and a['nfp'] is not None:
            pairs.append((t,brks[b],a['yfp'],a['nfp'],1.0-(a['yfp']+a['nfp']),STAKE)); active[b]=None
        elif a['yfp'] is None and a['nfp'] is None:   # neither leg filled: re-join current bids or cancel
            if yb[b]>0 and nob[b]>0 and (yb[b]+nob[b])<=1.0-MARGIN: a['py']=yb[b]; a['pn']=nob[b]
            else: active[b]=None
# end of auction: any half-filled pair is a NAKED directional leg (the arb's real risk/leakage)
for b in range(nbr):
    a=active[b]
    if a and (a['yfp'] is not None) != (a['nfp'] is not None):
        if a['yfp'] is not None: naked_y[b]+=STAKE
        else: naked_n[b]+=STAKE
tot_naked=sum(naked_y)+sum(naked_n)
P=pd.DataFrame(pairs,columns=['ts','bracket','yes_cost','no_cost','margin','size'])
if len(P):
    P['et']=pd.to_datetime(P.ts,unit='s',utc=True).dt.tz_convert(ET).dt.strftime('%m-%d %H:%M:%S')
    P['hrs_to_close']=(e-P.ts)/3600.0
P.to_csv(f"{OUT}/arb_july6_pairs.csv",index=False)
print("\n=== EVENT-DRIVEN MAKER PAIR ARB (tick by tick, no bars) ===")
print(f"completed riskless pairs: {len(P)} | naked half-filled legs at close: ${tot_naked:,.0f} notional (the directional risk the arb leaks)")
if len(P):
    print(f"median locked margin per pair: {100*P.margin.median():.2f}c | mean {100*P.margin.mean():.2f}c | total locked ${(P.margin*P['size']).sum():.2f} on ${P['size'].sum():,.0f} pair-notional")
    lasth=P[P.hrs_to_close<=1.0]; rest=P[P.hrs_to_close>1.0]
    print(f"\nLAST HOUR (the swings): {len(lasth)} pairs | median margin {100*lasth.margin.median() if len(lasth) else 0:.2f}c | locked ${(lasth.margin*lasth['size']).sum() if len(lasth) else 0:.2f}")
    print(f"REST of auction:        {len(rest)} pairs | median margin {100*rest.margin.median() if len(rest) else 0:.2f}c | locked ${(rest.margin*rest['size']).sum() if len(rest) else 0:.2f}")
    P['htc_bin']=pd.cut(P.hrs_to_close,[0,1,3,6,12,24,60],labels=['<1h','1-3h','3-6h','6-12h','12-24h','24h+'])
    g=P.groupby('htc_bin',observed=True).agg(pairs=('margin','size'),med_margin_c=('margin',lambda x:round(100*x.median(),2)))
    g['locked_$']=P.groupby('htc_bin',observed=True).apply(lambda d:round((d.margin*d['size']).sum(),2))
    print("\npairs by hours-to-close:"); print(g.to_string())
    if len(lasth): print("\nfirst 15 pairs in the LAST HOUR:"); print(lasth.head(15)[['et','bracket','yes_cost','no_cost','margin','size']].round(3).to_string(index=False))
else:
    print("No completed pairs (spread never allowed a sub-(1-margin) maker pair, or one leg never crossed).")
px['sec']=(px.ts//1000).astype('int64'); px['sp']=px.best_ask-px.best_bid; px['htc']=(e-px.sec)/3600.0
print(f"\nmedian bid-ask spread | last hour {px[px.htc<=1].sp.median():.3f} vs earlier {px[px.htc>1].sp.median():.3f}")
print(f"WROTE {OUT}/arb_july6_pairs.csv")
