"""Pure-maker momentum scalp - PRE-REGISTERED spec, event-driven trade-tape replay.

Claim under test: on a YES-contract trade tape, when a print jumps >=1.5x vs the last
print at-or-before t-60s (price in [0.05,0.35], trailing-24h notional > $50k), a resting
BUY at (P-0.01) that fills within 15s and exits via a resting SELL at entry+0.07 earns
positive net P&L.  Scope: maker-resting (NO taking anywhere; fee = 0 both sides).

Frozen spec (headline = mode "spec"):
  fill  : any print in (t, t+15s] with price <= P_entry (touch), different print, no partial
  exit  : any later print (ts > fill ts) with price >= P_entry+0.07, else settle at 1/0
  rebate: +0.01/share on EACH executed leg (NON-default; CLAUDE/auditor say default is 0)
Diagnostics (declared, not swept):
  "hardened" : strict through-fill (p < P_entry, p > P_exit) and rebate = 0
  "control"  : zero-edge control - SAME mechanics, SAME filters, but fires on EVERY eligible
               print (no momentum trigger). If the control is profitable the fill model is
               fantasy and the headline is NOT valid.

THE WALL: signal uses only prints with ts <= t (momentum ref, trailing notional). The
resolution (winning_bucket) is read only when closing an unexited position (scoring).
The confidence filter on auctions is part of the pre-registered universe (outcome-quality
selection, disclosed). Window = noon-ET from slug; prints at/after window end are dropped.

Usage:  python pure_maker_momentum_scalp.py [--root REPO_ROOT] [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_meta import emit_run_meta  # noqa: E402

ET = ZoneInfo("America/New_York")
SEED = 20260101
EPS = 1e-9

# ---- pre-registered constants -------------------------------------------------
LIQ_MIN = 50_000.0
P_LO, P_HI = 0.05, 0.35
RATIO_MIN = 1.50
LOOKBACK_S = 60.0
TTL_S = 15.0
ENTRY_OFFSET = 0.01
EXIT_OFFSET = 0.07
MIN_TICK = 0.01
REBATE_PER_LEG = 0.01
SIZE = 1.0
LIQ_WINDOW_S = 86_400.0
HANDLES = ["realDonaldTrump", "elonmusk"]
REQUIRED_COLS = ["ts", "price", "size", "outcome", "_bucket"]

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTHS.update({"january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7,
               "august": 8, "september": 9, "sept": 9, "october": 10, "november": 11,
               "december": 12})


def norm_bucket(s) -> str:
    return str(s).replace("–", "-").replace("—", "-").strip()


def noon_window(slug: str, year: int):
    """Slug -> (start_s, end_s) epoch seconds, noon ET to noon ET (DST-correct). None if unparseable."""
    s = slug.lower()
    m = re.search(r"-([a-z]+)-(\d{1,2})-([a-z]+)-(\d{1,2})(?:[-.]|$)", s)
    if m and m.group(1) in MONTHS and m.group(3) in MONTHS:
        mo1, d1, mo2, d2 = MONTHS[m.group(1)], int(m.group(2)), MONTHS[m.group(3)], int(m.group(4))
    else:
        m = re.search(r"-([a-z]+)-(\d{1,2})-(\d{1,2})(?:[-.]|$)", s)
        if not (m and m.group(1) in MONTHS):
            return None
        mo1 = mo2 = MONTHS[m.group(1)]
        d1, d2 = int(m.group(2)), int(m.group(3))
    try:
        y2 = year + (1 if mo2 < mo1 else 0)
        a = datetime(year, mo1, d1, 12, tzinfo=ET).timestamp()
        b = datetime(y2, mo2, d2, 12, tzinfo=ET).timestamp()
    except ValueError:
        return None
    if not (0.5 * 86400 <= b - a <= 9 * 86400):
        return None
    return a, b


def to_epoch_seconds(col: pd.Series) -> np.ndarray:
    if pd.api.types.is_numeric_dtype(col):
        v = col.astype("float64").to_numpy()
        mx = np.nanmax(v) if len(v) else 0
        div = 1e9 if mx > 1e17 else 1e6 if mx > 1e14 else 1e3 if mx > 1e11 else 1.0
        return v / div
    dt = pd.to_datetime(col, utc=True, errors="coerce")
    return ((dt - pd.Timestamp(0, tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                                       text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except Exception:
        return "unknown"


# ---- per-instrument simulation -------------------------------------------------
class Cfg:
    def __init__(self, name, strict, rebate):
        self.name, self.strict, self.rebate = name, strict, rebate


def simulate(ts, p, cand, is_winner, cfg: Cfg):
    """Walk candidate signal indices in tape order. Returns (orders, n_skipped_busy).

    ts/p are already truncated to < window end. is_winner: True/False/None(ambiguous).
    """
    out, skipped, busy_until = [], 0, -np.inf
    n = len(ts)
    for i in cand:
        t = ts[i]
        if t <= busy_until:           # position open or entry order pending -> skip
            skipped += 1
            continue
        pe = max(round(p[i] - ENTRY_OFFSET, 3), MIN_TICK)
        lo = np.searchsorted(ts, t, side="right")          # strictly after t: never the signal print
        hi = np.searchsorted(ts, t + TTL_S, side="right")
        seg = p[lo:hi]
        hit = np.nonzero(seg < pe - EPS)[0] if cfg.strict else np.nonzero(seg <= pe + EPS)[0]
        if len(hit) == 0:
            busy_until = t + TTL_S
            out.append(dict(i=i, t=t, pe=pe, status="cancelled"))
            continue
        fi = lo + hit[0]
        tf = ts[fi]
        px = round(pe + EXIT_OFFSET, 3)
        lo2 = np.searchsorted(ts, tf, side="right")        # exit print must be strictly later in time
        seg2 = p[lo2:n]
        h2 = np.nonzero(seg2 > px + EPS)[0] if cfg.strict else np.nonzero(seg2 >= px - EPS)[0]
        rec = dict(i=i, t=t, pe=pe, px=px, tf=tf, status="filled",
                   off_tick=bool(abs(pe * 100 - round(pe * 100)) > 1e-6))
        if len(h2):
            te = ts[lo2 + h2[0]]
            rec.update(exit="target", te=te, spread=px - pe, resolution=0.0,
                       rebate=2 * cfg.rebate * SIZE, excluded=False)
            busy_until = te
        else:
            rec.update(exit="resolution", te=np.inf, spread=0.0, rebate=cfg.rebate * SIZE)
            if is_winner is None:
                rec.update(resolution=0.0, excluded=True)       # Rule 7: never fabricate
            else:
                rec.update(resolution=(1.0 if is_winner else 0.0) - pe, excluded=False,
                           res_value=1.0 if is_winner else 0.0)
            busy_until = np.inf
        out.append(rec)
    return out, skipped


def build_signals(ts, p, sz, w_start):
    """Returns (mom_price_mask, liq_ok_mask, mom_mask) per print - all causal (<= t)."""
    n = len(ts)
    j = np.searchsorted(ts, ts - LOOKBACK_S, side="right") - 1      # last print at-or-before t-60s
    have = j >= 0
    ref = np.where(have, p[np.clip(j, 0, n - 1)], np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = p / ref
    mom = have & (ratio >= RATIO_MIN - EPS)
    cs = np.concatenate([[0.0], np.cumsum(p * sz)])
    lo = np.searchsorted(ts, ts - LIQ_WINDOW_S, side="right")
    idx = np.arange(n)
    liq = cs[idx + 1] - cs[lo]                                       # prints in (t-24h, t], index <= i
    in_bracket = (p >= P_LO - EPS) & (p <= P_HI + EPS) & (ts >= w_start)
    return in_bracket, liq > LIQ_MIN, mom, liq


# ---- stats helpers -------------------------------------------------------------
def summarize(trades: pd.DataFrame, n_breakouts_pre, n_breakouts_post, n_orders, n_cancel, n_skip):
    f = trades[trades.status == "filled"] if len(trades) else trades
    n_fill_all = len(f)
    excl = int(f.excluded.sum()) if n_fill_all else 0
    g = f[~f.excluded] if n_fill_all else f
    n = len(g)
    spread = float(g.spread.sum()) if n else 0.0
    rebate = float(g.rebate.sum()) if n else 0.0
    resn = float(g.resolution.sum()) if n else 0.0
    wins = int((g.exit == "target").sum()) if n else 0
    adverse = int(((g.exit == "resolution") & (g.res_value == 0.0)).sum()) if n else 0
    res = dict(
        breakouts_pre_liquidity=n_breakouts_pre, breakouts_post_filter=n_breakouts_post,
        orders_placed=n_orders, skipped_busy=n_skip, cancelled=n_cancel,
        filled_total=n_fill_all, excluded_n=excl, filled_scored=n,
        limit_fill_rate_pct_of_breakouts=100 * n_fill_all / n_breakouts_post if n_breakouts_post else None,
        limit_fill_rate_pct_of_orders=100 * n_fill_all / n_orders if n_orders else None,
        win_rate_pct=100 * wins / n if n else None,
        adverse_selection_rate=adverse / n if n else None,
        adverse_n=adverse, wins=wins,
        pnl=dict(spread_capture_pnl=spread, rebate_pnl=rebate, resolution_pnl=resn,
                 total=spread + rebate + resn, total_ex_rebate=spread + resn),
        off_tick_entry_frac=float(g.off_tick.mean()) if n else None,
    )
    return res, g


def drawdown(g: pd.DataFrame):
    if not len(g):
        return dict(max_dd_usd=0.0, max_dd_pct_of_peak_capital=None, max_dd_pct_of_peak_equity=None,
                    peak_capital_deployed=0.0), pd.DataFrame()
    e = g.sort_values(["tf", "t"], kind="stable").reset_index(drop=True)
    e["trade_pnl"] = e.spread + e.rebate + e.resolution
    e["cum_pnl"] = e.trade_pnl.cumsum()
    peak = np.maximum.accumulate(np.concatenate([[0.0], e.cum_pnl.to_numpy()]))[1:]
    e["drawdown"] = e.cum_pnl - peak
    dd = float(-e.drawdown.min())
    # capital deployed: +pe at fill, -pe at close (exit ts, or +inf -> end of tape)
    ev = [(r.tf, r.pe) for r in e.itertuples()] + [(r.te if np.isfinite(r.te) else r.tf + 1e12, -r.pe) for r in e.itertuples()]
    ev.sort(key=lambda x: (x[0], x[1]))
    cur = mx = 0.0
    for _, d in ev:
        cur += d
        mx = max(mx, cur)
    pk_eq = float(max(0.0, e.cum_pnl.max()))
    return dict(max_dd_usd=dd,
                max_dd_pct_of_peak_capital=100 * dd / mx if mx else None,
                max_dd_pct_of_peak_equity=100 * dd / pk_eq if pk_eq > 0 else None,
                peak_capital_deployed=mx), e


def by_auction_stats(g: pd.DataFrame, rng):
    if not len(g):
        return dict(n_auctions=0)
    a = (g.spread + g.rebate + g.resolution).groupby(g.auction).sum()
    v = a.to_numpy()
    n = len(v)
    boots = np.array([v[rng.integers(0, n, n)].sum() for _ in range(5000)])
    out = dict(n_auctions=n, total=float(v.sum()), boot_ci95_total=[float(np.percentile(boots, 2.5)),
               float(np.percentile(boots, 97.5))], mean_per_trade=float((g.spread + g.rebate + g.resolution).mean()))
    out["jackknife_drop_best_auction_total"] = float(v.sum() - v.max())
    out["best_auction"] = str(a.idxmax())
    out["best_auction_pnl"] = float(v.max())
    out["ci_includes_zero"] = bool(out["boot_ci95_total"][0] <= 0 <= out["boot_ci95_total"][1])
    if n < 10:
        out["note"] = "n<10 auctions: noise until more data"
    return out


# ---- main ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE.parents[1]))
    ap.add_argument("--out-dir", default=str(HERE))
    a = ap.parse_args()
    root, out = Path(a.root), Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    canon = root / "_DataMetricPulls" / "canonical"
    raw_dir = next((d for d in (canon / "_raw_imports" / "whale_analysis",
                                canon / "_raw_imports" / "api_trades_v2") if d.exists()), None)
    if raw_dir is None:
        sys.exit(f"ABORT: no raw trade archive under {canon}/_raw_imports/ "
                 f"(tried whale_analysis, api_trades_v2). Canonical data is gitignored - "
                 f"restore it / run scripts/canonical/*, or pass --root.")
    files = sorted(raw_dir.glob("*.parquet"))
    if not files:
        sys.exit(f"ABORT: {raw_dir} has no parquet files")

    # schema gate (first file) - fail loudly, never guess columns
    schema = pq.read_schema(files[0])
    missing = [c for c in REQUIRED_COLS if c not in schema.names]
    if missing:
        sys.exit(f"ABORT: {files[0].name} lacks required columns {missing}; has {schema.names}")

    # auctions (confidence filter is pre-registered universe definition)
    parts = [pd.read_parquet(f) for h in HANDLES for f in sorted((canon / "auctions" / h).glob("*.parquet"))]
    if not parts:
        sys.exit(f"ABORT: no canonical auctions under {canon}/auctions")
    auc_all = pd.concat(parts, ignore_index=True)
    auc = auc_all[auc_all.confidence.isin(["high", "medium"])].drop_duplicates("auction_slug")
    by_slug = auc.set_index("auction_slug")
    by_file = auc.drop_duplicates("source_file").set_index("source_file") if "source_file" in auc else None
    n_auc_total, n_auc_adm = len(auc_all), len(auc)

    cfgs = {"spec": Cfg("spec", False, REBATE_PER_LEG), "hardened": Cfg("hardened", True, 0.0)}
    led = {k: [] for k in ("spec", "hardened", "control_spec", "control_hardened")}
    cnt = {k: dict(pre=0, post=0, orders=0, cancel=0, skip=0) for k in led}
    univ = dict(files=len(files), files_not_admissible=0, files_dup_slug=0, files_window_unparseable=0,
                files_empty=0, auctions_used=0, instruments_pre=0, instruments_liq_ever=0,
                prints_total=0, prints_outside_window_dropped=0, auctions_winner_ambiguous=0)
    seen, tmin, tmax = set(), np.inf, -np.inf
    cols = [c for c in ["ts", "price", "size", "outcome", "_bucket", "eventSlug", "transactionHash"]
            if c in schema.names]

    for f in files:
        df = pq.read_table(f, columns=cols).to_pandas()
        if not len(df):
            univ["files_empty"] += 1
            continue
        slug = str(df["eventSlug"].iloc[0]) if "eventSlug" in df else None
        row = by_file.loc[f.name] if (by_file is not None and f.name in by_file.index) else (
            by_slug.loc[slug] if slug in by_slug.index else None)
        if row is None:
            univ["files_not_admissible"] += 1
            continue
        slug = row["auction_slug"] if "auction_slug" in row else slug
        if slug in seen:
            univ["files_dup_slug"] += 1
            continue
        yr = pd.Timestamp(row["start_utc"]).tz_convert(ET).year if "start_utc" in row else None
        win = noon_window(slug, yr) if yr else None
        if win is None:
            univ["files_window_unparseable"] += 1
            continue
        seen.add(slug)
        w0, w1 = win
        df["t"] = to_epoch_seconds(df["ts"])
        df = df.dropna(subset=["t", "price", "size"])
        if "transactionHash" in df:
            df = df.drop_duplicates(["transactionHash", "_bucket", "outcome", "price", "size"])
        if df["t"].max() - df["t"].min() > 0 and (np.mod(df["t"].to_numpy(), 60) == 0).all():
            sys.exit(f"ABORT: {f.name} timestamps are all minute-aligned (coarser than 1s)")
        df["_bucket"] = df["_bucket"].map(norm_bucket)
        df["yp"] = np.where(df["outcome"] == "Yes", df["price"], 1.0 - df["price"])
        univ["prints_total"] += len(df)
        inwin = df["t"] < w1                       # keep pre-start history for lookback; cap at window end
        univ["prints_outside_window_dropped"] += int((~inwin).sum())
        df = df[inwin]
        wb = norm_bucket(row["winning_bucket"] or "")
        buckets = set(df["_bucket"].unique())
        winner_ok = bool(wb) and "," not in wb and wb in buckets
        if not winner_ok:
            univ["auctions_winner_ambiguous"] += 1
        univ["auctions_used"] += 1
        for b, g in df.groupby("_bucket", sort=False):
            g = g.sort_values("t", kind="stable")
            ts, p, sz = g["t"].to_numpy(), g["yp"].to_numpy(), g["size"].to_numpy()
            tmin, tmax = min(tmin, ts[0]), max(tmax, ts[-1])
            univ["instruments_pre"] += 1
            inb, liq_ok, mom, _ = build_signals(ts, p, sz, w0)
            if (inb & liq_ok).any():
                univ["instruments_liq_ever"] += 1
            is_win = (b == wb) if winner_ok else None
            cand_sets = {"spec": np.nonzero(inb & mom)[0],
                         "hardened": np.nonzero(inb & mom)[0],
                         "control_spec": np.nonzero(inb & liq_ok)[0],
                         "control_hardened": np.nonzero(inb & liq_ok)[0]}
            n_pre = int((inb & mom).sum())
            for k, cand_pre in cand_sets.items():
                cfg = cfgs["spec" if k.endswith("spec") else "hardened"]
                is_ctrl = k.startswith("control")
                cand = cand_pre if is_ctrl else cand_pre[liq_ok[cand_pre]]
                c = cnt[k]
                c["pre"] += len(cand_pre) if not is_ctrl else len(cand)
                c["post"] += len(cand)
                orders, skipped = simulate(ts, p, cand, is_win, cfg)
                c["skip"] += skipped
                c["orders"] += len(orders)
                c["cancel"] += sum(o["status"] == "cancelled" for o in orders)
                for o in orders:
                    o.update(auction=slug, bucket=b, handle=row.get("handle", ""),
                             winner_bucket=wb, mode=k)
                    led[k].append(o)

    if not univ["auctions_used"]:
        sys.exit("ABORT: zero admissible auctions matched raw files")

    rng = np.random.default_rng(SEED)
    results, eq_frames, ledgers = {}, [], []
    for k in led:
        df = pd.DataFrame(led[k])
        for c in ("status", "excluded", "exit", "spread", "rebate", "resolution", "tf", "te", "pe", "t",
                  "off_tick", "res_value", "auction"):
            if c not in df:
                df[c] = np.nan if c not in ("status", "exit", "auction") else ""
        df["excluded"] = df["excluded"].fillna(False).astype(bool)
        c = cnt[k]
        res, g = summarize(df, c["pre"], c["post"], c["orders"], c["cancel"], c["skip"])
        res["drawdown"], eq = drawdown(g)
        res["by_auction"] = by_auction_stats(g, rng)
        results[k] = res
        if len(eq):
            eq_frames.append(eq.assign(mode=k))
        if len(df):
            ledgers.append(df.assign(mode=k))

    # liquidity filter before/after for the spec trigger
    results["spec"]["breakouts_pre_liquidity"] = int(cnt["spec"]["pre"])
    ctrl_bad = results["control_spec"]["pnl"]["total"] > 0
    verdict = ("CONTROL PROFITABLE under spec fills -> FILL MODEL IS FANTASY; headline NOT VALID"
               if ctrl_bad else "control not profitable under spec fills (necessary, not sufficient)")

    meta_block = dict(
        data_window_utc=[datetime.fromtimestamp(tmin, timezone.utc).isoformat(),
                         datetime.fromtimestamp(tmax, timezone.utc).isoformat()],
        universe=dict(auctions_total=n_auc_total, auctions_admissible_conf_high_medium=n_auc_adm, **univ),
        run_timestamp_utc=datetime.now(timezone.utc).isoformat(), git_sha=git_sha(), seed=SEED,
        raw_dir=str(raw_dir), spec_deviations=[
            "instrument = (auction file, _bucket) Yes-series; No prints mirrored as 1-price (files are per-auction, not per-contract)",
            "auctions with unparseable noon-ET slug window are excluded (reported), prints >= window end dropped",
            "signals only at ts >= window start; pre-start prints used for lookback only",
            "rebate +0.01/leg is the PRE-REGISTERED non-default; ex-rebate total reported alongside",
        ])
    final = dict(meta=meta_block, control_verdict=verdict, results=results)
    (out / "pure_maker_momentum_scalp_results.json").write_text(json.dumps(final, indent=2, default=str))
    if eq_frames:
        pd.concat(eq_frames).to_parquet(out / "pure_maker_momentum_scalp_equity.parquet", index=False)
    if ledgers:
        pd.concat(ledgers).to_parquet(out / "pure_maker_momentum_scalp_ledger.parquet", index=False)

    h = results["spec"]
    md = [f"# Pure-maker momentum scalp (spec) - run {meta_block['run_timestamp_utc']} git {meta_block['git_sha']}",
          "NEEDS @backtest-auditor REVIEW BEFORE ANY NUMBER IS TRUSTED.", f"**Control:** {verdict}", "",
          f"Window: {meta_block['data_window_utc'][0]} -> {meta_block['data_window_utc'][1]}",
          f"Universe: {n_auc_adm} admissible auctions; used {univ['auctions_used']}; instruments {univ['instruments_pre']} "
          f"(liq>50k ever: {univ['instruments_liq_ever']})", "",
          "| metric | spec | hardened | control(spec) | control(hardened) |", "|---|---|---|---|---|"]
    for lab, fn in [("breakouts pre-liq/ctrl elig", lambda r: r["breakouts_pre_liquidity"]),
                    ("breakouts post-filter", lambda r: r["breakouts_post_filter"]),
                    ("filled", lambda r: r["filled_total"]),
                    ("fill rate % (of breakouts)", lambda r: r["limit_fill_rate_pct_of_breakouts"]),
                    ("win rate %", lambda r: r["win_rate_pct"]),
                    ("adverse sel rate", lambda r: r["adverse_selection_rate"]),
                    ("spread pnl", lambda r: r["pnl"]["spread_capture_pnl"]),
                    ("rebate pnl", lambda r: r["pnl"]["rebate_pnl"]),
                    ("resolution pnl", lambda r: r["pnl"]["resolution_pnl"]),
                    ("TOTAL", lambda r: r["pnl"]["total"]), ("total ex-rebate", lambda r: r["pnl"]["total_ex_rebate"]),
                    ("max DD $", lambda r: r["drawdown"]["max_dd_usd"]),
                    ("max DD % peak capital", lambda r: r["drawdown"]["max_dd_pct_of_peak_capital"]),
                    ("excluded_n", lambda r: r["excluded_n"]),
                    ("n auctions w/ trades", lambda r: r["by_auction"].get("n_auctions"))]:
        cells = []
        for k in ("spec", "hardened", "control_spec", "control_hardened"):
            v = fn(results[k])
            cells.append("n/a" if v is None else f"{v:.4g}" if isinstance(v, float) else str(v))
        md.append(f"| {lab} | " + " | ".join(cells) + " |")
    md += ["", f"Spec by-auction CI/jackknife: {json.dumps(h['by_auction'], default=str)}", "",
           "Caveats: touch-fill/no-latency/no-queue under spec; hardened is strict-through + rebate 0 only (no queue haircut - UNVERIFIED).",
           "Deviations: " + "; ".join(meta_block["spec_deviations"])]
    (out / "pure_maker_momentum_scalp_results.md").write_text("\n".join(md))

    print(json.dumps({k: {x: v[x] for x in ("breakouts_post_filter", "filled_total", "limit_fill_rate_pct_of_breakouts",
                                              "win_rate_pct", "adverse_selection_rate", "pnl", "drawdown", "excluded_n")}
                      for k, v in results.items()}, indent=2, default=str))
    print("CONTROL:", verdict)
    emit_run_meta(
        script=__file__,
        headline=dict(n_auctions=h["by_auction"].get("n_auctions", 0), net_pnl_usdc=h["pnl"]["total"],
                      net_pnl_ex_rebate=h["pnl"]["total_ex_rebate"], fill_rate_pct=h["limit_fill_rate_pct_of_breakouts"],
                      win_rate_pct=h["win_rate_pct"], control_total_pnl_spec=results["control_spec"]["pnl"]["total"]),
        data_paths=[str(raw_dir), str(canon / "auctions")],
        window_basis="noon-ET parsed from slug; prints >= window end dropped",
        fills="maker-only, fee=0 both sides, taker=none; spec: touch fill p<=entry (no queue, no latency) + REBATE +0.01/leg (pre-registered, non-default); hardened: strict-through, rebate 0",
        trial_count=2, scope="maker-resting",
        notes="spec headline pre-registered; hardened + zero-edge control are declared diagnostics; no param sweep. " + verdict)


if __name__ == "__main__":
    main()
