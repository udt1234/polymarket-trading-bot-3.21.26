"""Shared helpers for the canonical builders.

Two things live here because more than one builder needs them:
  * path resolution (with an env override so a git worktree can point at the
    main checkout's gitignored _DataMetricPulls/)
  * winner-bracket price coverage, the invariant that broke silently in
    2026-01..2026-07 and produced an inverted backtest headline.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

ROOT = Path(os.environ.get("POLYBOT_ROOT") or Path(__file__).resolve().parents[2])
CANON = ROOT / "_DataMetricPulls" / "canonical"
RAW_DIR = CANON / "_raw_imports" / "api_trades_v2"
AUCTIONS_DIR = CANON / "auctions"
PRICES_DIR = CANON / "prices"

HANDLES = ["elonmusk", "realDonaldTrump"]

# Minimum share of admissible auctions whose winning bracket must have at least
# one price row. Below this the canonical layer is not fit for any backtest that
# scores a model against the market-implied distribution.
COVERAGE_FLOOR = 0.95


def normalize_bucket(s) -> str:
    """En-dash/em-dash -> hyphen, trim. Same rule as 08_normalize_bucket_labels."""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("–", "-").replace("—", "-").strip()


def load_partitioned(kind: str, handle: str) -> pd.DataFrame:
    files = sorted((CANON / kind / handle).glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)


def winner_coverage(handle: str, auctions: pd.DataFrame | None = None,
                    prices: pd.DataFrame | None = None) -> dict:
    """Share of admissible auctions whose winning bracket has >=1 price row.

    Admissible = confidence in (high, medium) and a single non-empty
    winning_bucket, i.e. exactly the filter CLAUDE.md tells backtests to apply.
    Returns per-duration_type counts plus an overall figure and the offending
    slugs, so callers can fail loudly and name names.
    """
    auc = load_partitioned("auctions", handle) if auctions is None else auctions
    prc = load_partitioned("prices", handle) if prices is None else prices
    if not len(auc) or not len(prc):
        return {"handle": handle, "n_admissible": 0, "n_covered": 0,
                "coverage": None, "by_duration": {}, "missing": []}

    prc = prc.assign(bucket=prc["bucket"].map(normalize_bucket))
    by_slug = prc.groupby("auction_slug")["bucket"].agg(set).to_dict()

    n_adm = n_cov = 0
    by_dur: dict[str, dict] = {}
    missing = []
    for _, r in auc.iterrows():
        if r.get("confidence") not in ("high", "medium"):
            continue
        wb = normalize_bucket(r.get("winning_bucket") or "")
        if not wb or wb == "nan" or "," in wb:
            continue
        dur = str(r.get("duration_type") or "unknown")
        d = by_dur.setdefault(dur, {"n": 0, "covered": 0})
        n_adm += 1
        d["n"] += 1
        if wb in by_slug.get(r["auction_slug"], set()):
            n_cov += 1
            d["covered"] += 1
        else:
            missing.append({"auction_slug": r["auction_slug"], "duration_type": dur,
                            "winning_bucket": wb,
                            "resolution_status": r.get("resolution_status")})
    for d in by_dur.values():
        d["coverage"] = d["covered"] / d["n"] if d["n"] else None
    return {"handle": handle, "n_admissible": n_adm, "n_covered": n_cov,
            "coverage": (n_cov / n_adm) if n_adm else None,
            "by_duration": by_dur, "missing": missing}


def format_coverage(rep: dict) -> str:
    cov = rep["coverage"]
    head = (f"  {rep['handle']}: winner price coverage "
            f"{rep['n_covered']}/{rep['n_admissible']}"
            f" ({'n/a' if cov is None else f'{100*cov:.1f}%'})")
    lines = [head]
    for dur, d in sorted(rep["by_duration"].items()):
        c = d["coverage"]
        lines.append(f"    {dur:<10} {d['covered']:>4}/{d['n']:<4}"
                     f" ({'n/a' if c is None else f'{100*c:.1f}%'})")
    return "\n".join(lines)


def assert_winner_coverage(handle: str, floor: float = COVERAGE_FLOOR,
                           hard: bool = False) -> dict:
    """Print coverage and, when below `floor`, warn loudly (or raise if hard).

    Never silently passes: a canonical layer whose winners have no market data
    inverts any model-vs-market comparison built on top of it.
    """
    rep = winner_coverage(handle)
    print(format_coverage(rep))
    cov = rep["coverage"]
    if cov is not None and cov < floor:
        msg = (f"WINNER COVERAGE BELOW FLOOR for {handle}: "
               f"{100*cov:.1f}% < {100*floor:.1f}% "
               f"({rep['n_admissible'] - rep['n_covered']} admissible auctions have no "
               f"price row for the bracket that won). Do NOT run model-vs-market "
               f"backtests on this data. Run 14_repair_bracket_coverage.py.")
        if hard:
            raise AssertionError(msg)
        print(f"  !! {msg}")
    return rep
