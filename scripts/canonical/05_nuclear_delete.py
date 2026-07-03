"""
Nuclear delete of messy _DataMetricPulls/ sources after canonical/ is built.

KEEPS:
  _DataMetricPulls/canonical/                  (the new canonical layer)
  _DataMetricPulls/canonical/_audit/           (historical audit)
  _DataMetricPulls/canonical/_raw_imports/     (frozen copy of api_trades_v2)
  _DataMetricPulls/duckdb_remote.py            (HF remote query helper, if present)
  _DataMetricPulls/trump_posts_raw.parquet     (source of posts canonical)
  _DataMetricPulls/elon_posts_raw.parquet      (source of posts canonical)
  _DataMetricPulls/__pycache__                 (will be reborn anyway)

DELETES:
  Every other subfolder and file directly under _DataMetricPulls/

Prints what it deletes. Dry-run by default; pass --confirm to actually delete.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DM = ROOT / "_DataMetricPulls"

KEEP = {
    "canonical",
    "trump_posts_raw.parquet",
    "elon_posts_raw.parquet",
    "duckdb_remote.py",
    "__pycache__",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()

    to_delete: list[Path] = []
    total_bytes = 0
    for entry in sorted(DM.iterdir()):
        if entry.name in KEEP:
            continue
        to_delete.append(entry)
        if entry.is_file():
            total_bytes += entry.stat().st_size
        elif entry.is_dir():
            for f in entry.rglob("*"):
                if f.is_file():
                    total_bytes += f.stat().st_size

    print(f"[delete] mode: {'CONFIRMED' if args.confirm else 'DRY RUN'}")
    print(f"[delete] would delete {len(to_delete)} entries totaling {total_bytes / 1e9:.2f} GB")
    print()
    for e in to_delete:
        kind = "dir " if e.is_dir() else "file"
        size_mb = sum(f.stat().st_size for f in e.rglob("*") if f.is_file()) / 1e6 if e.is_dir() else e.stat().st_size / 1e6
        print(f"  {kind} {size_mb:>9,.1f} MB  {e.name}")

    if not args.confirm:
        print()
        print("[delete] dry run only. re-run with --confirm to actually delete.")
        return 0

    print()
    print("[delete] DELETING...")
    for e in to_delete:
        try:
            if e.is_dir():
                shutil.rmtree(e)
            else:
                e.unlink()
            print(f"  deleted {e.name}")
        except Exception as ex:
            print(f"  ERR deleting {e.name}: {ex}")
    print(f"[delete] DONE. Freed ~{total_bytes / 1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
