# -*- coding: utf-8 -*-
"""Aggregate weather_reward_farm_replay.csv into the decisive NET numbers.

Portfolio convention: we quote EVERY observed weather market that passes the config's spread
gate, concurrently, at `size` shares per side. Capital deployed is MEASURED, not assumed:
    avg_concurrent_capital = sum(avg_capital * quote_minutes) / wall_clock_minutes
so annualized return-on-capital is honest about idle time and about how many markets were live
at once.

Three NET columns bracket the truth:
    net60    = reward + 60s MID mark-out   (optimistic: assumes you can exit at the mid)
    nettouch = reward + 60s TOUCH mark-out (realistic: exit a long into the bid, short into ask)
    netres   = reward + resolution         (pessimistic: inventory you never exit)
nettouch is the GO/NO-GO number.

Everything is reported PER MARKET-DAY as well as per calendar day, because a weather market only
lives ~7-8 hours in the reward band and per-calendar-day figures hide that.

Usage: python weather_reward_farm_report.py --span-days D [--csv PATH]
"""
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path("C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot")
KEY = ["defense", "gate_c", "quote_s_c", "size"]
FF = lambda x: f"{x:,.2f}"


def agg(df, span_days):
    wall_min = span_days * 1440.0
    g = df.groupby(KEY, as_index=False).agg(
        markets=("slug", "nunique"), market_days=("quote_days", "sum"),
        reward=("reward_usd", "sum"), mk60=("markout60_usd", "sum"),
        mktouch=("markouttouch_usd", "sum"), mkres=("markoutres_usd", "sum"),
        edge=("edge_usd", "sum"), fills=("fills", "sum"),
        filled_shares=("filled_shares", "sum"), mean_share=("avg_share", "mean"),
        mean_spread=("avg_mkt_spread_c", "mean"))
    capw = df.assign(cm=df.avg_capital * df.quote_minutes).groupby(KEY, as_index=False)["cm"].sum()
    g = g.merge(capw, on=KEY)
    g["capital"] = g.cm / wall_min
    g["net60"] = g.reward + g.mk60
    g["nettouch"] = g.reward + g.mktouch
    g["netres"] = g.reward + g.mkres
    for c in ("reward", "mk60", "mktouch", "mkres", "net60", "nettouch", "netres"):
        g[c + "_pmd"] = g[c] / g.market_days          # per MARKET-DAY
        g[c + "_day"] = g[c] / span_days              # per CALENDAR day (whole portfolio)
    g["ann_nettouch"] = g.nettouch_day * 365
    g["roc_pct"] = np.where(g.capital > 0, g.ann_nettouch / g.capital * 100, np.nan)
    g["bleed_over_reward"] = -g.mktouch / g.reward
    return g.drop(columns=["cm"])


def boot(pm, col, n=4000, seed=11):
    v = (pm[col] / pm["days"].replace(0, np.nan)).dropna().to_numpy()
    if len(v) < 5:
        return np.nan, np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    bs = np.array([rng.choice(v, len(v), True).mean() for _ in range(n)])
    return v.mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5), (bs <= 0).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(ROOT / "_DataMetricPulls/pacing_backtest/audit_out_weather_v2/weather_reward_farm_replay.csv"))
    ap.add_argument("--span-days", type=float, required=True)
    a = ap.parse_args()
    df = pd.read_csv(a.csv)
    pd.set_option("display.width", 320); pd.set_option("display.max_rows", 600)
    out = Path(a.csv).parent
    g = agg(df, a.span_days)
    per = df.groupby("slug").first()

    print(f"=== WEATHER REWARD-FARM REPLAY on real recorded L2 ({a.span_days:.2f}-day capture) ===")
    print(f"markets with usable data : {df.slug.nunique()}")
    print(f"reward rate: observed live from Gamma on {df[df.rate_observed].slug.nunique()} markets "
          f"(${per[per.rate_observed].rate.min():.0f}-{per[per.rate_observed].rate.max():.0f}/day); "
          f"the other {df.slug.nunique()-df[df.rate_observed].slug.nunique()} use the "
          f"$100/day recorder capture floor")
    print(f"resolution known for     : {per.res_yes.notna().sum()} markets "
          f"(YES resolved TRUE on {int((per.res_yes == 1).sum())})")
    print(f"market's own spread      : median {per.avg_mkt_spread_c.median():.1f}c  "
          f"p25 {per.avg_mkt_spread_c.quantile(.25):.1f}c  p75 {per.avg_mkt_spread_c.quantile(.75):.1f}c")
    print(f"in-band competing depth  : median {per.avg_comp_inband_depth.median():,.0f} shares "
          f"(competing Q median {per.avg_comp_q.median():,.0f})\n")

    cols = ["defense", "gate_c", "quote_s_c", "size", "markets", "market_days", "capital",
            "reward_pmd", "mk60_pmd", "mktouch_pmd", "mkres_pmd",
            "net60_pmd", "nettouch_pmd", "netres_pmd", "fills", "mean_share"]

    print("=== TOP 25 CONFIGS by nettouch per market-day (the honest NET) ===")
    print(g.sort_values("nettouch_pmd", ascending=False)[cols].head(25)
          .to_string(index=False, float_format=FF))

    print("\n=== SPREAD-GATE SWEEP (base defense) - the reward only pays where the book is untradeable ===")
    sub = g[g.defense == "base"].sort_values(["size", "gate_c", "quote_s_c"])
    print(sub[cols].to_string(index=False, float_format=FF))

    print("\n=== DEFENSES: best config per defense by nettouch_pmd ===")
    best = g.sort_values("nettouch_pmd", ascending=False).groupby("defense", as_index=False).first()
    print(best.sort_values("nettouch_pmd", ascending=False)[cols].to_string(index=False, float_format=FF))

    print("\n=== PORTFOLIO $/DAY and RETURN ON CAPITAL, top 12 by nettouch_day ===")
    pc = ["defense", "gate_c", "quote_s_c", "size", "markets", "capital", "reward_day",
          "mktouch_day", "nettouch_day", "net60_day", "netres_day", "ann_nettouch", "roc_pct"]
    print(g.sort_values("nettouch_day", ascending=False)[pc].head(12)
          .to_string(index=False, float_format=FF))

    g.to_csv(out / "weather_reward_farm_summary.csv", index=False)

    print("\n=== BOOTSTRAP over MARKETS (resample unit = market) for the headline configs ===")
    heads = (g.sort_values("nettouch_pmd", ascending=False).head(3)[KEY].values.tolist()
             + g.sort_values("net60_pmd", ascending=False).head(2)[KEY].values.tolist()
             + [["base", -1.0, 2.0, 100], ["base", 5.0, 2.0, 100]])
    seen = set()
    for d, gt, s, sz in heads:
        k = (d, gt, s, sz)
        if k in seen:
            continue
        seen.add(k)
        sub = df[(df.defense == d) & (df.gate_c == gt) & (df.quote_s_c == s) & (df["size"] == sz)]
        if sub.empty:
            continue
        pm = sub.groupby("slug").agg(nt=("nettouch_usd", "sum"), n6=("net60_usd", "sum"),
                                     nr=("netres_usd", "sum"), days=("quote_days", "sum"))
        line = f"  {d:16s} gate{gt:6.1f} s{s:4.1f} sz{sz:5.0f} n={len(pm):4d} |"
        for lbl, col in (("touch", "nt"), ("60s", "n6"), ("res", "nr")):
            m, lo, hi, p0 = boot(pm, col)
            line += f" {lbl}: ${m:9,.2f} CI[{lo:9,.2f},{hi:9,.2f}] P<=0 {p0:5.1%} |"
        print(line)

    b = g.sort_values("nettouch_pmd", ascending=False).iloc[0]
    sel = df[(df.defense == b.defense) & (df.gate_c == b.gate_c)
             & (df.quote_s_c == b.quote_s_c) & (df["size"] == b["size"])]
    pm = sel.groupby("slug").agg(nettouch=("nettouch_usd", "sum"), net60=("net60_usd", "sum"),
                                 netres=("netres_usd", "sum"), reward=("reward_usd", "sum"),
                                 days=("quote_days", "sum"), fills=("fills", "sum"))
    print(f"\n=== CONCENTRATION CHECK at the best-nettouch config "
          f"({b.defense} / gate {b.gate_c}c / s={b.quote_s_c}c / size={b['size']:.0f}) ===")
    print(f"nettouch>0 on {(pm.nettouch>0).sum()}/{len(pm)} markets ({(pm.nettouch>0).mean():.0%}); "
          f"total ${pm.nettouch.sum():,.0f}")
    print(f"top-1 market = {pm.nlargest(1,'nettouch').nettouch.iloc[0]/pm.nettouch.sum():.0%} of total; "
          f"top-5 = {pm.nlargest(5,'nettouch').nettouch.sum()/pm.nettouch.sum():.0%}")
    print(f"median ${pm.nettouch.median():,.2f}  p10 ${pm.nettouch.quantile(.1):,.2f}  "
          f"p90 ${pm.nettouch.quantile(.9):,.2f}  fills total {int(pm.fills.sum())}")
    pm.to_csv(out / "weather_reward_farm_per_market.csv")
    print(f"\nwrote {out/'weather_reward_farm_summary.csv'} and _per_market.csv")


if __name__ == "__main__":
    main()
