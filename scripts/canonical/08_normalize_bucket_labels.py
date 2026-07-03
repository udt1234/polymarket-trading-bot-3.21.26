"""
Normalize bucket label characters (en-dash to hyphen, trim whitespace) so
winning_bucket from Gamma can match raw api_trades_v2 bucket strings.

Then re-tag any auction whose winning_bucket STILL doesn't appear in the
prices table as confidence='low' (data structure mismatch — Polymarket
re-issued the market with different brackets mid-flight).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"


def normalize_bucket(s: str) -> str:
    """Replace en-dash/em-dash with hyphen, strip whitespace."""
    if not isinstance(s, str):
        return s
    return s.replace("–", "-").replace("—", "-").strip()


def process_handle(handle: str) -> tuple[int, int, int]:
    """Returns (n_normalized, n_demoted_to_low, n_unchanged)."""
    auc_files = sorted((CANON / "auctions" / handle).glob("*.parquet"))
    prc_files = sorted((CANON / "prices" / handle).glob("*.parquet"))
    if not auc_files or not prc_files:
        return (0, 0, 0)

    prc = pd.concat([pd.read_parquet(p) for p in prc_files], ignore_index=True)
    prc["bucket"] = prc["bucket"].apply(normalize_bucket)
    # rewrite prices partitions with normalized bucket labels
    for p in prc_files:
        sub = pd.read_parquet(p)
        sub["bucket"] = sub["bucket"].apply(normalize_bucket)
        sub.to_parquet(p, index=False)

    # auctions: normalize winning_bucket + bracket dicts + then validate against prices
    n_norm = n_demoted = n_unchanged = 0
    for af in auc_files:
        df = pd.read_parquet(af)
        df["winning_bucket"] = df["winning_bucket"].astype(str).apply(normalize_bucket)
        df["all_buckets"] = df["all_buckets"].astype(str).apply(
            lambda s: ", ".join(normalize_bucket(b) for b in s.split(","))
        )
        for col in ["bracket_condition_ids", "bracket_yes_token_ids", "bracket_no_token_ids"]:
            if col in df.columns:
                def _norm_dict(s):
                    try:
                        d = json.loads(s) if isinstance(s, str) else s
                        return json.dumps({normalize_bucket(k): v for k, v in d.items()})
                    except Exception:
                        return s
                df[col] = df[col].apply(_norm_dict)

        # now validate winning_bucket against prices for this auction
        for idx, row in df.iterrows():
            wb = (row.get("winning_bucket") or "").strip()
            if not wb:
                continue
            psub = prc[prc["auction_slug"] == row["auction_slug"]]
            if not len(psub):
                continue
            buckets = {b for b in psub["bucket"].unique()}
            if wb in buckets:
                if row["confidence"] != "low":
                    n_norm += 1
            else:
                # mismatch — demote
                if row["confidence"] != "low":
                    df.at[idx, "confidence"] = "low"
                    df.at[idx, "resolution_status"] = row["resolution_status"] + "_bracket_mismatch"
                    n_demoted += 1
        df.to_parquet(af, index=False)
        n_unchanged += len(df)
    return (n_norm, n_demoted, n_unchanged - n_norm - n_demoted)


def main():
    for h in ["realDonaldTrump", "elonmusk"]:
        print(f"[{h}] processing...")
        a, b, c = process_handle(h)
        print(f"  bucket-normalized (still matches): {a}")
        print(f"  demoted to confidence=low (bracket structure mismatch): {b}")
        print(f"  unchanged: {c}")
    print()
    print("Done. Re-run 07_consistency_test.py to confirm.")


if __name__ == "__main__":
    main()
