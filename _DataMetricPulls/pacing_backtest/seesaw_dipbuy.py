# -*- coding: utf-8 -*-
"""SIR'S ACTUAL STRATEGY: buy the DIP on 2 ALTERNATING (adjacent, seesawing) brackets, accrue shares,
hold to resolution. Event-driven, every price tick, NO bars. On the July-4-6 auction (recorder).

Mechanics (stated so a wrong one is easy to catch):
  - The 2 brackets = the adjacent pair with the highest average price over the window (the pair the
    count seesaws between). We trade only these two.
  - DIP-BUY: per bracket, keep an EMA of its price. When its ask dips >= DIP below its EMA, that
    bracket has faded -> buy a $TRANCHE tranche at the dip (maker: fill at the dipped ask). Cooldown
    so one fade = a few buys, not thousands. Cap total per bracket.
  - We naturally ALTERNATE: when A rises B fades (and vice versa), so the dips flip between them.
  - HOLD both to resolution. The winning bracket pays $1. Profit if our blended cost across the two
    is below $1 (we bought the winner cheap on its dips).
"""
import duckdb, sys, json, glob, os, urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
REC=f"{ROOT}/_DataMetricPulls/recordings_pulled"; OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
DIP=0.03; TRANCHE=50.0; COOLDOWN=180; MAXPOS=500.0; EMA_ALPHA=0.02  # knobs
SLUG='elon-musk-of-tweets-july-4-july-6'
def noon(slug):
    tk=slug.replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
s,e=noon(SLUG)
cands=[]
for p in ['elon-tweets-48h.parquet','elon-tweets-48h']:
    fp=os.path.join(REC,p)
    if os.path.isfile(fp): cands=[fp]; break
    if os.path.isdir(fp): cands=sorted(glob.glob(fp+'/*.parquet')); break
if not cands: cands=sorted(glob.glob(f"{REC}/*48h*.parquet"))
arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in cands)+"]"
px=con.execute(f"""SELECT ts, bucket, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
    WHERE slug='{SLUG}' AND outcome='YES' AND event_type='price_change' AND best_ask>0 AND best_ask<1
    AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
px['mid']=np.where(px.best_bid>0,(px.best_bid+px.best_ask)/2,px.best_ask)
def pbk(l):
    l=str(l).strip()
    if l.startswith('<'): return (0,int(l[1:])-1)
    if l.endswith('+'): return (int(l[:-1]),10**9)
    if '-' in l: a,b=l.split('-'); return (int(a),int(b))
    return (int(l),int(l))
allbr=sorted(px.bucket.dropna().unique(), key=lambda b:pbk(b)[0])
meanp=px.groupby('bucket').mid.mean()
# pick the adjacent pair with the highest combined average price
best=None; bestv=-1
for i in range(len(allbr)-1):
    a,b=allbr[i],allbr[i+1]; v=meanp.get(a,0)+meanp.get(b,0)
    if v>bestv: bestv=v; best=(a,b)
B=list(best)
# official winner from Gamma
try:
    req=urllib.request.Request(f"https://gamma-api.polymarket.com/events?slug={SLUG}",headers={'User-Agent':'Mozilla/5.0'})
    ev=json.loads(urllib.request.urlopen(req,timeout=30).read())[0]
    W=next(((m.get('groupItemTitle') or '').strip() for m in ev.get('markets',[]) if (json.loads(m['outcomePrices']) if isinstance(m.get('outcomePrices'),str) else m.get('outcomePrices'))==['1','0']),'?')
except Exception as ex: W='?'
print(f"AUCTION {SLUG} | window {datetime.fromtimestamp(s,ET):%m-%d %H:%M}->{datetime.fromtimestamp(e,ET):%m-%d %H:%M} ET | OFFICIAL WINNER {W}")
print(f"the 2 seesaw brackets (highest adjacent pair by avg price): {B[0]} (avg {meanp[B[0]]:.2f}) + {B[1]} (avg {meanp[B[1]]:.2f})")
print(f"knobs: DIP {DIP} below EMA | tranche ${TRANCHE:.0f} | cooldown {COOLDOWN}s | max ${MAXPOS:.0f}/bracket\n")

sub=px[px.bucket.isin(B)].copy()
ts=(sub.ts.to_numpy()//1000).astype('int64'); bk=sub.bucket.to_numpy(); ask=sub.best_ask.to_numpy(float); mid=sub.mid.to_numpy(float)
ema={b:None for b in B}; last_buy={b:-10**9 for b in B}; deployed={b:0.0 for b in B}; shares={b:0.0 for b in B}; cost={b:0.0 for b in B}
buys=[]
for i in range(len(ts)):
    t=ts[i]; b=bk[i]; m=mid[i]; a=ask[i]
    ema[b]=m if ema[b] is None else EMA_ALPHA*m+(1-EMA_ALPHA)*ema[b]
    if a <= ema[b]-DIP and t-last_buy[b]>=COOLDOWN and deployed[b]+TRANCHE<=MAXPOS:
        sh=TRANCHE/a; shares[b]+=sh; cost[b]+=TRANCHE; deployed[b]+=TRANCHE; last_buy[b]=t
        buys.append({'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M:%S'),'hrs_to_close':round((e-t)/3600,2),
            'bracket':b,'buy_price':round(a,3),'ema':round(ema[b],3),'dip':round(ema[b]-a,3),'shares':round(sh,1),'won':'WINNER' if b==W else 'loser'})
bd=pd.DataFrame(buys); bd.to_csv(f"{OUT}/seesaw_buys.csv",index=False)
print(f"=== SEESAW DIP-BUY (event-driven, {len(sub):,} ticks on the 2 brackets) ===")
print(f"total dip-buys: {len(bd)}  ({', '.join(f'{b}: {int((bd.bracket==b).sum())}' for b in B)})")
tot_cost=sum(cost.values()); payoff=sum(shares[b]*(1.0 if b==W else 0.0) for b in B); pnl=payoff-tot_cost
for b in B:
    ap=cost[b]/shares[b] if shares[b] else 0
    print(f"  {b:<8} shares {shares[b]:>7.0f} | avg cost {ap:.3f} | deployed ${cost[b]:>6.0f} | {'WON -> pays $'+format(shares[b],'.0f') if b==W else 'lost -> $0'}")
print(f"\n  combined cost ${tot_cost:,.0f} | payoff ${payoff:,.0f} (winner {W}) | P&L ${pnl:+,.0f} | ROI {100*pnl/tot_cost if tot_cost else 0:+.1f}%")
if len(bd):
    lh=bd[bd.hrs_to_close<=1]; print(f"\n  buys in the LAST HOUR: {len(lh)} | first 12:")
    print(lh.head(12)[['et','bracket','buy_price','ema','dip','shares','won']].to_string(index=False) if len(lh) else "   none")
    print(f"\n  buys by hours-to-close:")
    bd['htc']=pd.cut(bd.hrs_to_close,[0,1,3,6,12,24,60],labels=['<1h','1-3h','3-6h','6-12h','12-24h','24h+'])
    print(bd.groupby('htc',observed=True).agg(n=('bracket','size'),avg_price=('buy_price','mean')).round(3).to_string())
print(f"\nWROTE {OUT}/seesaw_buys.csv")
