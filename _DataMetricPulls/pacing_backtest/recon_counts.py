import sys, numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls')
CANON = ROOT/'canonical'; OUT = ROOT/'pacing_backtest'
auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
res = pd.read_csv(OUT/'backtest_full_results.csv')
res['start_dt'] = pd.to_datetime(res['start_utc'], utc=True)
A = auc.set_index('auction_slug')

def parse_bucket(lbl):
    lbl=str(lbl).strip()
    try:
        if lbl.startswith('<'): return (0, int(lbl[1:])-1)
        if lbl.endswith('+'): return (int(lbl[:-1]), None)
        if '-' in lbl: a,b=lbl.split('-'); return (int(a),int(b))
        return (int(lbl),int(lbl))
    except: return None
def mid(lbl):
    rg=parse_bucket(lbl)
    if not rg: return None
    lo,hi=rg
    return lo if hi is None else (lo+hi)/2

rows=[]
for _,r in res.iterrows():
    slug=r['auction_slug']; actual=float(r['actual'])
    win=A.loc[slug,'winning_bucket'] if slug in A.index else None
    gwin=A.loc[slug,'gamma_winning_bucket'] if slug in A.index else None
    rstat=A.loc[slug,'resolution_status'] if slug in A.index else None
    rg=parse_bucket(win) if win else None
    inside = bool(rg and rg[0]<=actual<=(rg[1] if rg[1] is not None else 1e12))
    m=mid(win)
    rows.append(dict(slug=slug, dur=r['duration_type'], start=r['start_dt'],
                     actual=actual, winner=win, gamma_winner=gwin, rstat=rstat,
                     inside=inside, wmid=m, ratio=(actual/m if m else np.nan),
                     odd=any(x in slug for x in ['arch-','higher-bra','lower-bra','-lower','-higher'])))
d=pd.DataFrame(rows).sort_values('start')

print(f'Total auctions scored: {len(d)}')
print(f'actual INSIDE winning_bucket: {d.inside.sum()}/{len(d)} ({100*d.inside.mean():.0f}%)')
print(f'winning_bucket == gamma_winning_bucket: {(d.winner==d.gamma_winner).sum()}/{len(d)}')
print(f'"odd" split/arch markets: {d.odd.sum()}')
print(f'\ninside-rate EXCLUDING odd markets: {d[~d.odd].inside.mean()*100:.0f}%  (n={(~d.odd).sum()})')
print(f'inside-rate for monthly only: {d[d.dur=="monthly"].inside.mean()*100:.0f}%  (n={(d.dur=="monthly").sum()})')

print('\n=== ratio (my counted actual / winning-bucket midpoint) over time ===')
d2=d.dropna(subset=["ratio"])
d2=d2[~d2.odd]
d2['period']=d2['start'].dt.to_period('Q').astype(str)
print(d2.groupby('period').agg(n=('ratio','size'), median_ratio=('ratio','median'),
                               median_actual=('actual','median'), median_wmid=('wmid','median')).to_string())

print('\n=== sample monthly mismatches (clean markets) ===')
mo=d[(d.dur=="monthly")][['start','actual','winner','gamma_winner','inside']].copy()
mo['start']=mo['start'].dt.date
print(mo.to_string(index=False))
