"""Phase 15 - assert the canonical layer's winner-bracket price coverage.

The invariant: for every auction a backtest is allowed to use
(confidence in high/medium), the bracket that WON must have at least one row in
canonical/prices. When it does not, a model-vs-market comparison scores the
model against a market distribution that excludes the outcome deciding the
score. In the 2026-07-26 pattern-discovery study that turned "market beats
naive extrapolation" (-0.37) into "naive beats the market" (+3.34).

Modes:
  (default)   report coverage per handle/duration; exit 1 if below the floor
  --demote    additionally re-tag uncovered auctions confidence='low' +
              resolution_status suffix '_no_winner_price', so the documented
              `confidence in ('high','medium')` filter excludes them
  --json PATH write the machine-readable report

Run after 04_build_prices.py. Wire into any pipeline that rebuilds canonical.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _canon import (  # noqa: E402
    AUCTIONS_DIR, CANON, COVERAGE_FLOOR, HANDLES, format_coverage,
    load_partitioned, normalize_bucket, winner_coverage,
)

DEMOTE_SUFFIX = "_no_winner_price"
ADMISSIBILITY_CSV = CANON / "_audit" / "winner_admissibility.csv"


def admissibility_table() -> pd.DataFrame:
    """Per-auction checkpoint gate for model-vs-market work.

    'The winner has a price somewhere in this auction' is not enough. On Elon
    7-day markets Polymarket extends the bracket ladder mid-flight, so the
    winning bracket often did not EXIST for the first half of the auction. A
    checkpoint before `winner_first_hour_utc` has no market view of the winner
    and is inadmissible, even though the auction passes the coverage gate.
    Join on auction_slug and drop checkpoints at T < winner_first_hour_utc.
    """
    rows = []
    for handle in HANDLES:
        auc = load_partitioned("auctions", handle)
        prc = load_partitioned("prices", handle)
        if not len(auc) or not len(prc):
            continue
        prc = prc.assign(bucket=prc["bucket"].map(normalize_bucket))
        first_any = prc.groupby("auction_slug")["hour_utc"].min()
        last_any = prc.groupby("auction_slug")["hour_utc"].max()
        grp = prc.groupby(["auction_slug", "bucket"])["hour_utc"]
        first_b, last_b, n_b = grp.min(), grp.max(), grp.size()
        for _, r in auc.iterrows():
            wb = normalize_bucket(r.get("winning_bucket") or "")
            slug = str(r["auction_slug"])
            key = (slug, wb)
            has = key in first_b.index
            rows.append({
                "handle": handle,
                "auction_slug": slug,
                "duration_type": r.get("duration_type"),
                "confidence": r.get("confidence"),
                "resolution_status": r.get("resolution_status"),
                "winning_bucket": wb,
                "auction_first_hour_utc": first_any.get(slug),
                "auction_last_hour_utc": last_any.get(slug),
                "winner_first_hour_utc": first_b.get(key) if has else None,
                "winner_last_hour_utc": last_b.get(key) if has else None,
                "winner_price_hours": int(n_b.get(key, 0)),
                "winner_lead_gap_h": (
                    (first_b.loc[key] - first_any.loc[slug]).total_seconds() / 3600.0
                    if has and slug in first_any.index else None),
                "admissible_vs_market": bool(has and r.get("confidence") in ("high", "medium")),
            })
    return pd.DataFrame(rows)


def demote(handle: str, missing_slugs: set[str]) -> int:
    """Re-tag uncovered auctions so the standard admissibility filter drops them."""
    n = 0
    for p in sorted((AUCTIONS_DIR / handle).glob("*.parquet")):
        df = pd.read_parquet(p)
        hit = df["auction_slug"].astype(str).isin(missing_slugs)
        if not hit.any():
            continue
        for idx in df.index[hit]:
            if df.at[idx, "confidence"] == "low":
                continue
            st = str(df.at[idx, "resolution_status"] or "")
            df.at[idx, "confidence"] = "low"
            if not st.endswith(DEMOTE_SUFFIX):
                df.at[idx, "resolution_status"] = st + DEMOTE_SUFFIX
            n += 1
        df.to_parquet(p, index=False)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor", type=float, default=COVERAGE_FLOOR)
    ap.add_argument("--demote", action="store_true",
                    help="re-tag uncovered auctions confidence='low'")
    ap.add_argument("--json", type=Path,
                    default=CANON / "_audit" / "winner_coverage.json")
    args = ap.parse_args()

    reports = {}
    failed = []
    print("[15] winner-bracket price coverage")
    for handle in HANDLES:
        rep = winner_coverage(handle)
        reports[handle] = rep
        print(format_coverage(rep))
        if rep["coverage"] is not None and rep["coverage"] < args.floor:
            failed.append(handle)

    if args.demote:
        print("\n[15] demoting uncovered auctions to confidence='low'")
        for handle in HANDLES:
            slugs = {m["auction_slug"] for m in reports[handle]["missing"]}
            if not slugs:
                continue
            n = demote(handle, slugs)
            print(f"  {handle}: demoted {n} auctions")
        print("\n[15] coverage after demotion (admissible set shrinks, coverage -> 100%)")
        for handle in HANDLES:
            reports[handle + "_after_demote"] = r = winner_coverage(handle)
            print(format_coverage(r))
        failed = []

    tab = admissibility_table()
    ADMISSIBILITY_CSV.parent.mkdir(parents=True, exist_ok=True)
    tab.to_csv(ADMISSIBILITY_CSV, index=False)
    late = tab[tab["winner_lead_gap_h"].fillna(0) > 0]
    print(f"\n[15] checkpoint gate -> {ADMISSIBILITY_CSV}")
    print(f"  {len(late)} auctions where the winning bracket was listed AFTER the auction "
          f"opened (Polymarket extends the ladder mid-flight).")
    print("  Any checkpoint at T < winner_first_hour_utc has no market view of the winner "
          "and is inadmissible even though the auction passes the coverage gate.")
    for dur, g in tab.dropna(subset=["winner_lead_gap_h"]).groupby("duration_type"):
        print(f"    {str(dur):<10} n={len(g):<4} lead_gap_h median={g['winner_lead_gap_h'].median():.0f} "
              f"p90={g['winner_lead_gap_h'].quantile(0.9):.0f} max={g['winner_lead_gap_h'].max():.0f}")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(
        {"floor": args.floor, "demoted": args.demote, "reports": reports},
        indent=2, default=str), encoding="utf-8")
    print(f"\n[15] report: {args.json}")

    if failed:
        print(f"\n[15] FAIL: {failed} below the {100*args.floor:.0f}% floor. "
              f"Run 14_repair_bracket_coverage.py, then 04_build_prices.py. "
              f"If the remaining gap is genuinely unpullable, re-run with --demote "
              f"so backtests exclude those auctions instead of scoring against a "
              f"market distribution that omits the winner.")
        return 1
    print("\n[15] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
