"""
Backtest: noovd-style 'cheap marginal-bin, buy-Yes, hold-to-resolution' edge.

Core claim being tested:
  Low-priced (tail/marginal) brackets are systematically UNDER-priced because
  retail crowds the center bin. Buying cheap Yes bins and holding to settlement
  is +EV. Turnover = 1 (entry only; settlement pays $1/$0, no exit trade).

This is the MODEL-FREE lower bound on noovd: we buy EVERY bin under a price
threshold (no fair-value model picking the best ones). If even this dumb version
is +EV, noovd's model selectivity is gravy. If it's -EV, the edge lives entirely
in model quality.

No look-ahead: entry decision uses only the price at entry time. winning_bucket
is the realized settlement outcome (that IS the P&L target, not a feature).
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, numpy as np
from pathlib import Path

CANON = Path("_DataMetricPulls/canonical")
OUT = CANON / "_backtests"
OUT.mkdir(exist_ok=True)

FRACS = [0.25, 0.50, 0.75]          # entry point: fraction of auction life elapsed
THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25]   # buy every bin priced <= T
SLIPPAGES = [0.0, 0.01, 0.02]       # additive per-share entry cost (taker spread proxy)


def load(handle):
    a = pd.concat([pd.read_parquet(p) for p in (CANON/"auctions"/handle).glob("*.parquet")])
    a = a.drop_duplicates(subset="auction_slug", keep="first")
    a = a[(a.confidence == "high") & (a.resolution_status == "resolved_yes")]
    a = a[a.winning_bucket.astype(str).str.len() > 0]
    pr = pd.concat([pd.read_parquet(p) for p in (CANON/"prices"/handle).glob("*.parquet")])
    return a, pr


def entry_prices(prdf, frac):
    """For one auction's price rows, return {bucket: entry_close} at frac of life."""
    hours = np.sort(prdf.hour_utc.unique())
    if len(hours) < 2:
        return {}
    t0, t1 = hours[0], hours[-1]
    target = t0 + (t1 - t0) * frac
    out = {}
    for b, g in prdf.groupby("bucket"):
        g = g.sort_values("hour_utc")
        # nearest available hour at-or-before target; else earliest after
        le = g[g.hour_utc <= target]
        row = le.iloc[-1] if len(le) else g.iloc[0]
        out[b] = float(row.close)
    return out


def build_obs(a, pr, handle):
    rows = []
    pr_by = dict(tuple(pr.groupby("auction_slug")))
    for _, au in a.iterrows():
        sub = pr_by.get(au.auction_slug)
        if sub is None:
            continue
        win = au.winning_bucket
        for frac in FRACS:
            ep = entry_prices(sub, frac)
            if win not in ep:                 # need the winner priced to be fair
                continue
            for b, p in ep.items():
                if not (0.0 < p < 1.0):
                    continue
                rows.append(dict(handle=handle, auction=au.auction_slug,
                                 end=au.end_utc, dur=au.duration_type, frac=frac,
                                 bucket=b, price=p, won=int(b == win)))
    return pd.DataFrame(rows)


def calibration(obs):
    bins = [0, .05, .10, .20, .35, .50, 1.0]
    labs = ["1-5c", "5-10c", "10-20c", "20-35c", "35-50c", "50c+"]
    o = obs.copy()
    o["pb"] = pd.cut(o.price, bins=bins, labels=labs)
    g = o.groupby("pb", observed=True).agg(n=("won", "size"),
                                           implied=("price", "mean"),
                                           realized=("won", "mean"))
    g["edge"] = g.realized - g.implied
    g["edge_per_$1_staked"] = g.realized / g.implied - 1.0
    return g


def threshold_pnl(obs, frac):
    o = obs[obs.frac == frac]
    res = []
    for T in THRESHOLDS:
        sel = o[o.price <= T]
        n_au = sel.auction.nunique()
        for slip in SLIPPAGES:
            cost = (sel.price + slip).sum()
            payout = sel.won.sum()
            roi = (payout - cost) / cost if cost > 0 else np.nan
            res.append(dict(frac=frac, threshold=T, slip=slip,
                            n_bins=len(sel), n_auctions=n_au,
                            cost=round(cost, 2), payout=int(payout),
                            net=round(payout - cost, 2), roi=round(roi, 4)))
    return pd.DataFrame(res)


def walkforward(obs, frac, T, slip):
    """Cumulative net P&L over time (1 share per qualifying bin), first vs second half."""
    o = obs[(obs.frac == frac) & (obs.price <= T)].copy()
    o["pnl"] = o.won - (o.price + slip)
    per_au = o.groupby(["auction", "end"]).pnl.sum().reset_index().sort_values("end")
    per_au["cum"] = per_au.pnl.cumsum()
    half = len(per_au) // 2
    h1, h2 = per_au.iloc[:half], per_au.iloc[half:]
    return per_au, h1.pnl.sum(), h2.pnl.sum()


def main():
    allobs = {}
    for h in ["elonmusk", "realDonaldTrump"]:
        a, pr = load(h)
        obs = build_obs(a, pr, h)
        allobs[h] = obs
        print("=" * 70)
        print(f"{h}: {a.auction_slug.nunique()} resolved high-conf auctions | "
              f"{obs.auction.nunique()} usable | {len(obs)} bin-observations")
        print("=" * 70)
        print("\nCALIBRATION (all entry points pooled) — is cheap underpriced?")
        print(calibration(obs).to_string(float_format=lambda x: f"{x:.4f}"))
        for frac in FRACS:
            print(f"\nTHRESHOLD P&L  (entry at {int(frac*100)}% of auction life):")
            print(threshold_pnl(obs, frac).to_string(index=False))
        # headline walk-forward at a representative config
        pa, s1, s2 = walkforward(obs, 0.50, 0.20, 0.01)
        print(f"\nWALK-FORWARD (entry 50%, buy<=20c, slip 1c):")
        print(f"  total net (1 share/bin): {pa.pnl.sum():.2f} over {len(pa)} auctions | "
              f"1st-half {s1:.2f} | 2nd-half {s2:.2f}")
        obs.to_csv(OUT / f"noovd_obs_{h}.csv", index=False)
    print(f"\nSaved per-bin observations to {OUT}/noovd_obs_*.csv")


if __name__ == "__main__":
    main()
