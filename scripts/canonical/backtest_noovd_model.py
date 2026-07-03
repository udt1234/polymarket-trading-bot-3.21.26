"""
Model-driven noovd backtest: Gamma-Poisson fair value vs market, buy cheap
under-priced Yes bins, hold to resolution. NO look-ahead.

Fair value at entry time t (uses only info available at t):
  count_so_far = counted posts in [window_start, t]
  elapsed/remaining in days from the noon-ET window
  rate lambda ~ Gamma(a0+count_so_far, b0+elapsed)        # weak prior, conjugate
  remaining posts ~ NegBin predictive (Gamma-Poisson) over `remaining` days
     -> fat tails, the right shape for Elon's bursts
  P(bucket) = P(lo <= count_so_far+remaining <= hi)

Strategy: among bins priced <= PMAX, BUY Yes where model_prob >= price * EDGE.
Hold to settlement. P&L = win - (entry_price + slippage). One crossing only.

Data-quality gate (outcome-independent): only auctions ending >= 2026-01-01,
where post history is complete (pre-2026 Elon/Trump data is undercounted by the
2025 OSINT scrape and would poison the model). winning_bucket used ONLY for P&L.
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, numpy as np
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from scipy.stats import nbinom

CANON = Path("_DataMetricPulls/canonical"); OUT = CANON/"_backtests"
ET = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}

# ---- model + grid params ----
PRIOR_MEAN_RATE = 40.0   # posts/day, weak anchor for periods of silence
PRIOR_DAYS      = 0.5     # prior strength in days (small = weak)
A0, B0 = PRIOR_MEAN_RATE * PRIOR_DAYS, PRIOR_DAYS
FRACS  = [0.25, 0.50]
PMAX   = 0.10            # tail focus (v1 showed edge dies above ~10c)
EDGES  = [1.0, 1.5, 2.0]  # require model_prob >= price * EDGE
SLIPS  = [0.0, 0.005, 0.01]


def pbk(b):
    b = str(b).strip()
    if b.startswith("<"): return (0, int(re.findall(r"\d+", b)[0]) - 1)
    if b.endswith("+"):   return (int(re.findall(r"\d+", b)[0]), 10**9)
    n = re.findall(r"\d+", b)
    return (int(n[0]), int(n[1])) if len(n) >= 2 else (None, None)


def pw(slug, ry):
    seq = []
    for t in slug.lower().split("-"):
        if t in MONTHS: seq.append(("m", MONTHS[t]))
        elif t.isdigit(): seq.append(("d", int(t)))
    md, cm = [], None
    for k, v in seq:
        if k == "m": cm = v
        elif cm and 1 <= v <= 31: md.append((cm, v))
    if len(md) < 2: return None
    (m1, d1), (m2, d2) = md[0], md[-1]; y2 = ry + 1 if m2 < m1 else ry
    try:
        s = datetime(ry, m1, d1, 12, tzinfo=ET); e = datetime(y2, m2, d2, 12, tzinfo=ET)
    except ValueError:
        return None
    return (pd.Timestamp(s).tz_convert("UTC"), pd.Timestamp(e).tz_convert("UTC")) if e > s else None


def model_prob(count_so_far, remaining_days, lo, hi):
    """P(lo<=final<=hi) via Gamma-Poisson (NegBin) predictive for remaining count."""
    a_post = A0 + count_so_far
    b_post = B0 + 0.0   # elapsed already folded into count via the conditional below
    # predictive over remaining exposure tau: N ~ NB(n=a_post, p=b_post/(b_post+tau))
    tau = max(remaining_days, 1e-6)
    p = b_post / (b_post + tau)
    klo = max(lo - count_so_far, 0)
    khi = hi - count_so_far
    if khi < 0:                      # bracket already impossible (count exceeded ceiling)
        return 0.0
    lo_cdf = nbinom.cdf(klo - 1, a_post, p) if klo > 0 else 0.0
    return float(nbinom.cdf(khi, a_post, p) - lo_cdf)


def entry_prices(prdf, frac, t0, t1):
    target = t0 + (t1 - t0) * frac
    out = {}
    for b, g in prdf.groupby("bucket"):
        g = g.sort_values("hour_utc"); le = g[g.hour_utc <= target]
        row = le.iloc[-1] if len(le) else g.iloc[0]
        out[b] = float(row.close)
    return out


def run(handle):
    a = pd.concat([pd.read_parquet(x) for x in (CANON/"auctions"/handle).glob("*.parquet")]).drop_duplicates("auction_slug")
    a = a[(a.confidence == "high") & (a.resolution_status == "resolved_yes")]
    a["ey"] = pd.to_datetime(a.end_utc, utc=True)
    a = a[a.ey >= pd.Timestamp("2026-01-01", tz="UTC")]          # complete-data window
    p = pd.concat([pd.read_parquet(x) for x in (CANON/"posts"/handle).glob("*.parquet")])
    p = p[p.counts_for_auction == True]; ts = pd.to_datetime(p.ts_utc, utc=True).sort_values()
    pr = pd.concat([pd.read_parquet(x) for x in (CANON/"prices"/handle).glob("*.parquet")])
    pr_by = dict(tuple(pr.groupby("auction_slug")))

    obs = []
    used = 0
    for _, r in a.iterrows():
        w = pw(r.auction_slug, pd.to_datetime(r.start_et).year)
        sub = pr_by.get(r.auction_slug)
        if w is None or sub is None: continue
        ws, we = w; win = r.winning_bucket
        hours = np.sort(sub.hour_utc.unique())
        if len(hours) < 2: continue
        used += 1
        for frac in FRACS:
            t = ws + (we - ws) * frac
            count_sf = int((ts >= ws).values.sum() and ((ts >= ws) & (ts < t)).sum())
            remaining_days = (we - t).total_seconds() / 86400
            eps = entry_prices(sub, frac, hours[0], hours[-1])
            for b, price in eps.items():
                lo, hi = pbk(b)
                if lo is None or not (0 < price < 1): continue
                mp = model_prob(count_sf, remaining_days, lo, hi)
                obs.append(dict(handle=handle, auction=r.auction_slug, end=r.ey, frac=frac,
                                bucket=b, price=price, model=mp, won=int(b == win),
                                is_win_bucket=int(b == win)))
    return pd.DataFrame(obs), used


def summarize(obs, used, handle):
    print("=" * 72)
    print(f"{handle}: {used} clean 2026 auctions | {len(obs)} bin-observations")
    print("=" * 72)
    # model discrimination: does model_prob rank the eventual winner high among <=PMAX bins?
    for frac in FRACS:
        o = obs[obs.frac == frac]
        print(f"\n--- entry {int(frac*100)}% | tail bins price<= {PMAX:.2f} ---")
        tail = o[o.price <= PMAX]
        base = tail.won.mean() if len(tail) else float("nan")
        print(f"baseline buy-ALL-<= {PMAX:.0%}: {len(tail)} bins, win rate {base:.1%}, "
              f"avg price {tail.price.mean():.3f}")
        for edge in EDGES:
            sel = tail[tail.model >= tail.price * edge]
            if not len(sel):
                print(f"  EDGE>= {edge}x: no trades"); continue
            line = f"  EDGE>= {edge}x: {len(sel):4d} bins | win {sel.won.mean():.1%} | avgP {sel.price.mean():.3f} | modP {sel.model.mean():.3f}"
            for slip in SLIPS:
                cost = (sel.price + slip).sum(); roi = (sel.won.sum() - cost) / cost
                line += f" | ROI@{int(slip*1000)}m {roi:+.0%}"
            print(line)
    return obs


def main():
    allobs = []
    for h in ["elonmusk", "realDonaldTrump"]:
        obs, used = run(h)
        if len(obs):
            summarize(obs, used, h)
            obs.to_csv(OUT/f"noovd_model_obs_{h}.csv", index=False)
            allobs.append(obs)
    print(f"\nSaved to {OUT}/noovd_model_obs_*.csv")
    print(f"ROI columns: @0m=maker(0c) @5m=0.5c @10m=1.0c slippage; EDGE=model_prob/price hurdle")


if __name__ == "__main__":
    main()
