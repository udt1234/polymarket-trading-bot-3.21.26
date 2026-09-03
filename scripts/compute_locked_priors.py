"""Compute the LOCKED pace-model priors offline and store them in Supabase.

Why offline: the live bot runs pure stdlib (no numpy/pandas/parquet), and the priors
(baseline rate, Kalman gain, accrual curve) change slowly - they are fitted from daily
noon-anchored windows over weeks. So we fit them here (dev box, has pandas) and store
them in the settings table; the live path just reads the dict and calls
locked_pace.project_locked(). Re-run this weekly (or after a big cadence shift).

  python scripts/compute_locked_priors.py                # elonmusk, 2-day + 7-day
  python scripts/compute_locked_priors.py --dry-run      # print, don't write

Stored under key `locked_pace_priors:{handle}:{dur_h}` = {rmean, Kk, share, fitted_at,
n_posts, model_version}.
"""
import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.modules.shared.locked_pace import MODEL_VERSION, build_priors  # noqa: E402

ET = ZoneInfo("America/New_York")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# X-API clean Elon history (memory: model ONLY on this; canonical/OSINT undercount ~2x)
ELON_PARQUET = os.path.join(ROOT, "_DataMetricPulls", "pacing_backtest",
                            "elon_backfill_2025-09_to_now.parquet")


def _load_post_ts(handle: str) -> list:
    import pandas as pd
    if handle != "elonmusk":
        raise SystemExit(f"no clean post-history source wired for {handle}")
    df = pd.read_parquet(ELON_PARQUET)
    if "counts_main_feed" in df.columns:
        df = df[df.counts_main_feed]
    ms = df["ms"].to_numpy().astype("int64")
    return sorted(int(m // 1000) for m in ms)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", default="elonmusk")
    ap.add_argument("--durations", default="48,168", help="comma list of window hours")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    post_ts = _load_post_ts(a.handle)
    now = int(datetime.now(tz=ET).timestamp())
    # a reference noon-ET boundary to anchor the daily windows on
    noon_epoch = int(datetime.now(tz=ET).replace(hour=12, minute=0, second=0,
                                                 microsecond=0).timestamp())
    print(f"{a.handle}: {len(post_ts)} posts, "
          f"{datetime.fromtimestamp(post_ts[0], ET):%Y-%m-%d} -> "
          f"{datetime.fromtimestamp(post_ts[-1], ET):%Y-%m-%d}")

    out = {}
    for dur_h in [float(x) for x in a.durations.split(",")]:
        pri = build_priors(post_ts, now, dur_h, noon_epoch)
        if not pri:
            print(f"  {dur_h:.0f}h: NOT ENOUGH HISTORY (<4 windows) - skipped")
            continue
        rmean, Kk, share = pri
        key = f"locked_pace_priors:{a.handle}:{int(dur_h)}"
        out[key] = {"rmean": round(rmean, 6), "Kk": round(Kk, 6),
                    "share": [round(s, 6) for s in share],
                    "fitted_at": datetime.now(tz=ET).isoformat(),
                    "n_posts": len(post_ts), "model_version": MODEL_VERSION}
        print(f"  {dur_h:.0f}h: rmean={rmean:.3f}/hr  Kk={Kk:.4f}  "
              f"share[{len(share)}] first={share[0]:.3f} last={share[-1]:.3f}")

    if a.dry_run:
        print("\n--dry-run: nothing written")
        return
    from api.dependencies import get_supabase
    sb = get_supabase()
    for key, val in out.items():
        sb.table("settings").upsert({"key": key, "value": val}).execute()
        print(f"stored {key}")


if __name__ == "__main__":
    main()
