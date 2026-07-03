"""
Calibrated pace-projection model for Elon tweet-count brackets — X-API posts ONLY.

Fixes the overdispersed Gamma-Poisson: instead of assuming a parametric tail,
we LEARN the dispersion from realized projection errors (leave-one-out), so the
predictive distribution is calibrated by construction.

At entry fraction f of the window:
  count_so_far = c ;  point projection  proj = c / f         (linear pace)
  predictive final  =  proj * R,  where R = {actual_i / proj_i} from ALL OTHER
                       auctions (leave-one-out -> no look-ahead, auto-corrects
                       any systematic front/back-loading bias)
  P(bracket [lo,hi]) = fraction of proj*R samples landing in [lo,hi]

Then the honest tests (print BEFORE any ROI):
  1. Reliability table — must be ~diagonal.
  2. Brier + argmax-hit vs the MARKET's own implied distribution. The model only
     has edge if it BEATS the market here, not merely matches it.
  3. ROI of betting model-vs-market disagreement, by price band, maker/taker.

Posts: _DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet only.
winning_bucket used ONLY for scoring/P&L.
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, numpy as np
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

CANON = Path("_DataMetricPulls/canonical"); OUT = CANON/"_backtests"
XAPI = Path("_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet")
ET = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}
FRACS = [0.25, 0.50]
EDGES = [1.5, 2.0]          # bet model_prob >= market_price * EDGE
SLIPS = [0.0, 0.01]


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


def load_counts():
    d = pd.read_parquet(XAPI)
    counted = d.type.isin(["original", "quote", "repost"]) | ((d.type == "reply") & (d.self_reply == True))
    return pd.to_datetime(d[counted].ts_utc, utc=True, format="ISO8601").sort_values().values


def entry_prices(prdf, frac, t0, t1):
    target = t0 + (t1 - t0) * frac
    out = {}
    for b, g in prdf.groupby("bucket"):
        g = g.sort_values("hour_utc"); le = g[g.hour_utc <= target]
        out[b] = float((le.iloc[-1] if len(le) else g.iloc[0]).close)
    return out


def gather(frac):
    """One record per auction: proj, actual, strip prices, winner, duration."""
    cts = load_counts(); lo_cov, hi_cov = cts.min(), cts.max()
    a = pd.concat([pd.read_parquet(x) for x in (CANON/"auctions/elonmusk").glob("*.parquet")]).drop_duplicates("auction_slug")
    a = a[(a.confidence == "high") & (a.resolution_status == "resolved_yes")]
    pr = pd.concat([pd.read_parquet(x) for x in (CANON/"prices/elonmusk").glob("*.parquet")])
    pr_by = dict(tuple(pr.groupby("auction_slug")))
    recs = []
    for _, r in a.iterrows():
        if str(r.auction_slug).startswith("arch-"): continue
        w = pw(r.auction_slug, pd.to_datetime(r.start_et).year)
        sub = pr_by.get(r.auction_slug)
        if w is None or sub is None: continue
        ws, we = w
        if np.datetime64(ws) < lo_cov or np.datetime64(we) > hi_cov: continue
        hours = np.sort(sub.hour_utc.unique())
        if len(hours) < 2: continue
        t = ws + (we - ws) * frac
        c = int(((cts >= np.datetime64(ws)) & (cts < np.datetime64(t))).sum())
        actual = int(((cts >= np.datetime64(ws)) & (cts < np.datetime64(we))).sum())
        if c <= 0: continue
        proj = c / frac
        prices = {b: p for b, p in entry_prices(sub, frac, hours[0], hours[1] if len(hours) > 1 else hours[0]).items()
                  if 0 < p < 1}
        prices = {b: p for b, p in entry_prices(sub, frac, hours[0], hours[-1]).items() if 0 < p < 1}
        recs.append(dict(slug=r.auction_slug, dur=r.duration_type, proj=proj, actual=actual,
                         win=r.winning_bucket, prices=prices))
    return recs


def run_frac(frac):
    recs = gather(frac)
    n = len(recs)
    projs = np.array([x["proj"] for x in recs]); acts = np.array([x["actual"] for x in recs])
    rows = []
    for j, rj in enumerate(recs):
        ratios = acts[np.arange(n) != j] / projs[np.arange(n) != j]   # leave-one-out
        samples = rj["proj"] * ratios
        # normalize market to implied probs across the strip
        tot = sum(rj["prices"].values())
        for b, price in rj["prices"].items():
            lo, hi = pbk(b)
            if lo is None: continue
            mp = float(((samples >= lo) & (samples <= hi)).mean())
            rows.append(dict(slug=rj["slug"], dur=rj["dur"], bucket=b, price=price,
                             mkt_impl=price/tot if tot else np.nan, model=mp,
                             won=int(b == rj["win"])))
    return pd.DataFrame(rows), n


def reliability(o, col):
    b = [0, .02, .05, .1, .2, .35, .5, .7, 1.01]
    oo = o.copy(); oo["pb"] = pd.cut(oo[col], bins=b)
    return oo.groupby("pb", observed=True).agg(n=("won", "size"), pred=(col, "mean"), realized=("won", "mean"))


def main():
    for frac in FRACS:
        o, n = run_frac(frac)
        print("=" * 74)
        print(f"ELON calibrated pace model | entry {int(frac*100)}% | {n} auctions | {len(o)} bins")
        print("=" * 74)

        print("\nRELIABILITY — model (leave-one-out):")
        print(reliability(o, "model").to_string(float_format=lambda x: f"{x:.3f}"))

        # head-to-head vs market
        brier_m = ((o.model - o.won) ** 2).mean()
        brier_k = ((o.mkt_impl - o.won) ** 2).mean()
        # argmax per auction
        mod_hit = o.loc[o.groupby("slug").model.idxmax()].won.mean()
        mkt_hit = o.loc[o.groupby("slug").mkt_impl.idxmax()].won.mean()
        print(f"\nHEAD-TO-HEAD vs MARKET:")
        print(f"  Brier  model {brier_m:.4f}  vs  market {brier_k:.4f}  "
              f"({'MODEL better' if brier_m < brier_k else 'market better'})")
        print(f"  argmax-picks-winner  model {mod_hit:.0%}  vs  market {mkt_hit:.0%}")

        print("\nROI of betting disagreement (model >= price*EDGE), by price band:")
        for edge in EDGES:
            sel = o[o.model >= o.price * edge]
            for lobnd, hibnd, lab in [(0, .10, "<=10c"), (.10, .35, "10-35c"), (.35, 1.0, "35c+"), (0, 1.0, "ALL")]:
                s = sel[(sel.price > lobnd) & (sel.price <= hibnd)]
                if len(s) < 3:
                    print(f"  EDGE{edge} {lab:7s}: {len(s):3d} bins (too few)"); continue
                line = f"  EDGE{edge} {lab:7s}: {len(s):3d} bins | win {s.won.mean():.0%} | avgP {s.price.mean():.3f}"
                for slip in SLIPS:
                    cost = (s.price + slip).sum(); line += f" | ROI@{int(slip*100)}c {(s.won.sum()-cost)/cost:+.0%}"
                print(line)
        o.to_csv(OUT/f"noovd_calib_obs_f{int(frac*100)}.csv", index=False)
    print(f"\nSaved {OUT}/noovd_calib_obs_*.csv  |  model must BEAT market Brier for any edge to be real")


if __name__ == "__main__":
    main()
