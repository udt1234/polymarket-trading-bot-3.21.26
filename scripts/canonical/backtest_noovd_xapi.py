"""
Model-driven noovd backtest — ELON, X-API post data ONLY.

Post source (the ONLY Elon tweet data used here):
  _DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet
  (Twitter/X API full pull, 2025-09-01 -> 2026-06-20, validated 82-86% to
   winning buckets with misses only off-by-one bracket at boundaries — vs the
   canonical/OSINT data which undercounts ~2x.)

Count rule (LOCKED Elon rule): originals + quotes + reposts + self-replies;
exclude pure replies and community reposts.

Everything else mirrors backtest_noovd_model.py: no look-ahead Gamma-Poisson
(NegBin) fair value, buy <=PMAX bins where model_prob >= price*EDGE, hold to
settlement, plus a model reliability table. winning_bucket used ONLY for P&L.
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, numpy as np
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from scipy.stats import nbinom

CANON = Path("_DataMetricPulls/canonical"); OUT = CANON/"_backtests"
XAPI = Path("_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet")
ET = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}

PRIOR_MEAN_RATE, PRIOR_DAYS = 40.0, 0.5
A0, B0 = PRIOR_MEAN_RATE*PRIOR_DAYS, PRIOR_DAYS
FRACS = [0.25, 0.50]
PMAX  = 0.10
EDGES = [1.0, 1.5, 2.0]
SLIPS = [0.0, 0.005, 0.01]


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


def model_prob(count_sf, remaining_days, lo, hi):
    a_post = A0 + count_sf
    tau = max(remaining_days, 1e-6); p = B0 / (B0 + tau)
    klo = max(lo - count_sf, 0); khi = hi - count_sf
    if khi < 0: return 0.0
    lo_cdf = nbinom.cdf(klo - 1, a_post, p) if klo > 0 else 0.0
    return float(nbinom.cdf(khi, a_post, p) - lo_cdf)


def load_xapi_counts():
    d = pd.read_parquet(XAPI)
    counted = d.type.isin(["original", "quote", "repost"]) | ((d.type == "reply") & (d.self_reply == True))
    ts = pd.to_datetime(d[counted].ts_utc, utc=True, format="ISO8601").sort_values()
    return ts.reset_index(drop=True)


def entry_prices(prdf, frac, t0, t1):
    target = t0 + (t1 - t0) * frac
    out = {}
    for b, g in prdf.groupby("bucket"):
        g = g.sort_values("hour_utc"); le = g[g.hour_utc <= target]
        out[b] = float((le.iloc[-1] if len(le) else g.iloc[0]).close)
    return out


def run():
    cts = load_xapi_counts()
    lo_cov, hi_cov = cts.min(), cts.max()
    a = pd.concat([pd.read_parquet(x) for x in (CANON/"auctions/elonmusk").glob("*.parquet")]).drop_duplicates("auction_slug")
    a = a[(a.confidence == "high") & (a.resolution_status == "resolved_yes")]
    pr = pd.concat([pd.read_parquet(x) for x in (CANON/"prices/elonmusk").glob("*.parquet")])
    pr_by = dict(tuple(pr.groupby("auction_slug")))
    cvals = cts.values

    obs, used = [], 0
    for _, r in a.iterrows():
        if str(r.auction_slug).startswith("arch-"):  # combined/arch markets: skip
            continue
        w = pw(r.auction_slug, pd.to_datetime(r.start_et).year)
        sub = pr_by.get(r.auction_slug)
        if w is None or sub is None: continue
        ws, we = w
        if ws < lo_cov or we > hi_cov: continue       # only inside X-API coverage
        hours = np.sort(sub.hour_utc.unique())
        if len(hours) < 2: continue
        used += 1
        win = r.winning_bucket
        for frac in FRACS:
            t = ws + (we - ws) * frac
            count_sf = int(((cvals >= np.datetime64(ws)) & (cvals < np.datetime64(t))).sum())
            remaining_days = (we - t).total_seconds() / 86400
            for b, price in entry_prices(sub, frac, hours[0], hours[-1]).items():
                lo, hi = pbk(b)
                if lo is None or not (0 < price < 1): continue
                obs.append(dict(auction=r.auction_slug, end=r.end_utc, frac=frac, bucket=b,
                                price=price, model=model_prob(count_sf, remaining_days, lo, hi),
                                won=int(b == win)))
    return pd.DataFrame(obs), used, (lo_cov, hi_cov)


def reliability(o):
    b = [0, .02, .05, .1, .2, .4, .7, 1.01]
    o = o.copy(); o["mb"] = pd.cut(o.model, bins=b)
    g = o.groupby("mb", observed=True).agg(n=("won", "size"), model_mean=("model", "mean"), realized=("won", "mean"))
    return g


def main():
    obs, used, cov = run()
    print("=" * 72)
    print(f"ELON (X-API posts only) | coverage {cov[0].date()}..{cov[1].date()} | "
          f"{used} auctions | {len(obs)} bin-obs")
    print("=" * 72)
    for frac in FRACS:
        o = obs[obs.frac == frac]; tail = o[o.price <= PMAX]
        print(f"\n--- entry {int(frac*100)}% | tail price<= {PMAX:.2f} ---")
        print(f"baseline buy-ALL: {len(tail)} bins | win {tail.won.mean():.1%} | avgP {tail.price.mean():.3f}")
        for edge in EDGES:
            sel = tail[tail.model >= tail.price * edge]
            if not len(sel): print(f"  EDGE>= {edge}x: no trades"); continue
            line = f"  EDGE>= {edge}x: {len(sel):3d} bins | win {sel.won.mean():.1%} | avgP {sel.price.mean():.3f} | modP {sel.model.mean():.3f}"
            for slip in SLIPS:
                cost = (sel.price + slip).sum(); line += f" | ROI@{int(slip*1000)}m {(sel.won.sum()-cost)/cost:+.0%}"
            print(line)
    print("\nMODEL RELIABILITY (entry 25%, all bins) — is model_prob calibrated now?")
    print(reliability(obs[obs.frac == 0.25]).to_string(float_format=lambda x: f"{x:.3f}"))
    obs.to_csv(OUT/"noovd_xapi_obs_elon.csv", index=False)
    print(f"\nSaved {OUT}/noovd_xapi_obs_elon.csv")


if __name__ == "__main__":
    main()
