"""
Phase 1: Source audit.

Walks _DataMetricPulls/ + Supabase archive + duckdb caches.
For every parquet / JSON / sqlite / duckdb file found, records:
  path, format, table_name, n_rows, date_min, date_max, handle,
  columns_json, sha256, size_mb, mtime

Output: _DataMetricPulls/canonical/_audit/source_inventory.csv

Read-only. Safe to re-run. ~1-2 min on a warm disk.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "_DataMetricPulls"
OUT_DIR = DATA_ROOT / "canonical" / "_audit"
OUT_CSV = OUT_DIR / "source_inventory.csv"

# columns that, when present, likely carry a timestamp we can min/max
TIMESTAMP_HINTS = (
    "ts", "timestamp", "created_at", "createdat", "createdAt",
    "dt_utc", "date", "datetime", "hour", "time", "imported_at",
    "importedAt", "end_date", "start_date", "endDate", "startDate",
    "auction_start_utc", "auction_end_utc", "snapshot_at", "snapshotAt",
)

HANDLE_HINTS = ("elon", "musk", "trump", "real_donald", "realdonaldtrump")


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def infer_handle_from_path(path: Path) -> str:
    s = str(path).lower()
    if "elon" in s or "musk" in s:
        return "elonmusk"
    if "trump" in s or "real_donald" in s or "realdonaldtrump" in s:
        return "realDonaldTrump"
    return ""


def find_time_range(df: pd.DataFrame) -> tuple[str, str, str]:
    """Return (col_used, min_str, max_str). Empty strings if nothing found."""
    if df is None or len(df) == 0:
        return ("", "", "")
    # try exact name hits first, then case-insensitive
    cols_lower = {c.lower(): c for c in df.columns}
    for hint in TIMESTAMP_HINTS:
        if hint in df.columns:
            col = hint
        elif hint.lower() in cols_lower:
            col = cols_lower[hint.lower()]
        else:
            continue
        try:
            s = pd.to_datetime(df[col], utc=True, errors="coerce")
            s = s.dropna()
            if len(s) == 0:
                continue
            return (col, str(s.min()), str(s.max()))
        except Exception:
            continue
    return ("", "", "")


def audit_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return [{
            "path": str(path.relative_to(ROOT)),
            "format": "parquet",
            "table": "",
            "n_rows": -1,
            "n_cols": -1,
            "columns_json": "",
            "time_col": "",
            "date_min": "",
            "date_max": "",
            "handle": infer_handle_from_path(path),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(path.stat().st_mtime)),
            "sha256": "",
            "error": f"{type(e).__name__}: {e}",
        }]
    col_used, dmin, dmax = find_time_range(df)
    return [{
        "path": str(path.relative_to(ROOT)),
        "format": "parquet",
        "table": "",
        "n_rows": len(df),
        "n_cols": df.shape[1],
        "columns_json": json.dumps(list(df.columns)),
        "time_col": col_used,
        "date_min": dmin,
        "date_max": dmax,
        "handle": infer_handle_from_path(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(path.stat().st_mtime)),
        "sha256": sha256_of(path),
        "error": "",
    }]


def audit_csv(path: Path) -> list[dict[str, Any]]:
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as e:
        return [{
            "path": str(path.relative_to(ROOT)),
            "format": "csv",
            "table": "",
            "n_rows": -1, "n_cols": -1, "columns_json": "",
            "time_col": "", "date_min": "", "date_max": "",
            "handle": infer_handle_from_path(path),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(path.stat().st_mtime)),
            "sha256": "",
            "error": f"{type(e).__name__}: {e}",
        }]
    col_used, dmin, dmax = find_time_range(df)
    return [{
        "path": str(path.relative_to(ROOT)),
        "format": "csv",
        "table": "",
        "n_rows": len(df),
        "n_cols": df.shape[1],
        "columns_json": json.dumps(list(df.columns)),
        "time_col": col_used,
        "date_min": dmin,
        "date_max": dmax,
        "handle": infer_handle_from_path(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(path.stat().st_mtime)),
        "sha256": sha256_of(path),
        "error": "",
    }]


def audit_json(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception as e:
        return [{
            "path": str(path.relative_to(ROOT)),
            "format": "json",
            "table": "",
            "n_rows": -1, "n_cols": -1, "columns_json": "",
            "time_col": "", "date_min": "", "date_max": "",
            "handle": infer_handle_from_path(path),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(path.stat().st_mtime)),
            "sha256": "",
            "error": f"{type(e).__name__}: {e}",
        }]
    # try the "list of dicts" shape, then "dict of dicts"
    df = None
    try:
        if isinstance(obj, list):
            df = pd.DataFrame(obj)
        elif isinstance(obj, dict):
            # common shape: { key: { ... } } -> records keyed by some id
            if all(isinstance(v, dict) for v in obj.values()):
                df = pd.DataFrame(list(obj.values()))
            else:
                df = pd.DataFrame([obj])
    except Exception:
        df = None
    n_rows = len(df) if df is not None else -1
    n_cols = df.shape[1] if df is not None else -1
    cols = list(df.columns) if df is not None else []
    col_used, dmin, dmax = ("", "", "")
    if df is not None:
        col_used, dmin, dmax = find_time_range(df)
    return [{
        "path": str(path.relative_to(ROOT)),
        "format": "json",
        "table": "",
        "n_rows": n_rows,
        "n_cols": n_cols,
        "columns_json": json.dumps(cols),
        "time_col": col_used,
        "date_min": dmin,
        "date_max": dmax,
        "handle": infer_handle_from_path(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(path.stat().st_mtime)),
        "sha256": sha256_of(path),
        "error": "",
    }]


def audit_sqlite_or_duckdb(path: Path) -> list[dict[str, Any]]:
    """For .db / .duckdb files, list tables and row counts."""
    rows: list[dict[str, Any]] = []
    base = {
        "path": str(path.relative_to(ROOT)),
        "format": path.suffix.lstrip(".").lower(),
        "handle": infer_handle_from_path(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(path.stat().st_mtime)),
        "sha256": sha256_of(path),
    }
    # try sqlite first (will work for sqlite .db). Skip duckdb (binary incompat).
    if path.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM \"{t}\"")
                    n = cur.fetchone()[0]
                except Exception as e:
                    n = -1
                try:
                    cur.execute(f"PRAGMA table_info(\"{t}\")")
                    cols = [r[1] for r in cur.fetchall()]
                except Exception:
                    cols = []
                # try to find a time col + min/max
                time_col = ""
                dmin = dmax = ""
                for hint in TIMESTAMP_HINTS:
                    if hint in cols:
                        try:
                            cur.execute(f"SELECT MIN(\"{hint}\"), MAX(\"{hint}\") FROM \"{t}\"")
                            r = cur.fetchone()
                            if r and r[0] is not None:
                                time_col = hint
                                dmin, dmax = str(r[0]), str(r[1])
                                break
                        except Exception:
                            continue
                rows.append({
                    **base,
                    "table": t,
                    "n_rows": n,
                    "n_cols": len(cols),
                    "columns_json": json.dumps(cols),
                    "time_col": time_col,
                    "date_min": dmin,
                    "date_max": dmax,
                    "error": "",
                })
            con.close()
            return rows
        except Exception as e:
            return [{
                **base, "table": "", "n_rows": -1, "n_cols": -1,
                "columns_json": "", "time_col": "", "date_min": "", "date_max": "",
                "error": f"sqlite: {type(e).__name__}: {e}",
            }]
    # duckdb file — try duckdb if available, else record metadata only
    if path.suffix.lower() == ".duckdb":
        try:
            import duckdb  # type: ignore
            con = duckdb.connect(str(path), read_only=True)
            try:
                tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
            except Exception:
                tables = []
            for t in tables:
                try:
                    n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception:
                    n = -1
                try:
                    cols = [r[1] for r in con.execute(f'DESCRIBE "{t}"').fetchall()]
                except Exception:
                    cols = []
                time_col = ""
                dmin = dmax = ""
                for hint in TIMESTAMP_HINTS:
                    if hint in cols:
                        try:
                            r = con.execute(f'SELECT MIN("{hint}"), MAX("{hint}") FROM "{t}"').fetchone()
                            if r and r[0] is not None:
                                time_col = hint
                                dmin, dmax = str(r[0]), str(r[1])
                                break
                        except Exception:
                            continue
                rows.append({
                    **base,
                    "table": t,
                    "n_rows": n,
                    "n_cols": len(cols),
                    "columns_json": json.dumps(cols),
                    "time_col": time_col,
                    "date_min": dmin,
                    "date_max": dmax,
                    "error": "",
                })
            con.close()
            return rows
        except Exception as e:
            return [{
                **base, "table": "", "n_rows": -1, "n_cols": -1,
                "columns_json": "", "time_col": "", "date_min": "", "date_max": "",
                "error": f"duckdb: {type(e).__name__}: {e}",
            }]
    return rows


SKIP_DIRS = {"__pycache__", "canonical", ".git", "node_modules", "audit_logs"}
SKIP_SUFFIXES_SIDECAR = {".db-shm", ".db-wal", ".duckdb-wal", ".duckdb-shm"}


def walk_files() -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(DATA_ROOT):
        # skip noisy / non-data dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            p = Path(dirpath) / fname
            sfx = p.suffix.lower()
            # explicit skip for sqlite/duckdb sidecar files
            if any(str(p).endswith(s) for s in SKIP_SUFFIXES_SIDECAR):
                continue
            if sfx in (".parquet", ".csv", ".json", ".db", ".sqlite", ".sqlite3", ".duckdb"):
                found.append(p)
    return found


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = walk_files()
    print(f"[audit] scanning {len(files)} files under {DATA_ROOT}")
    rows: list[dict[str, Any]] = []
    for i, p in enumerate(files, 1):
        sfx = p.suffix.lower()
        try:
            if sfx == ".parquet":
                rs = audit_parquet(p)
            elif sfx == ".csv":
                rs = audit_csv(p)
            elif sfx == ".json":
                rs = audit_json(p)
            elif sfx in (".db", ".sqlite", ".sqlite3", ".duckdb"):
                rs = audit_sqlite_or_duckdb(p)
            else:
                continue
            rows.extend(rs)
        except Exception as e:
            rows.append({
                "path": str(p.relative_to(ROOT)),
                "format": sfx.lstrip("."),
                "table": "", "n_rows": -1, "n_cols": -1,
                "columns_json": "", "time_col": "", "date_min": "", "date_max": "",
                "handle": infer_handle_from_path(p),
                "size_mb": round(p.stat().st_size / 1024 / 1024, 3),
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(p.stat().st_mtime)),
                "sha256": "",
                "error": f"{type(e).__name__}: {e}",
            })
        if i % 25 == 0:
            print(f"[audit] {i}/{len(files)} processed")
    # write CSV
    cols_out = [
        "path", "format", "table", "handle",
        "n_rows", "n_cols", "size_mb", "mtime",
        "time_col", "date_min", "date_max",
        "columns_json", "sha256", "error",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols_out)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols_out})
    print(f"[audit] wrote {len(rows)} rows to {OUT_CSV}")
    # print a quick summary to stdout
    df = pd.DataFrame(rows)
    if len(df):
        print("\n=== summary by format ===")
        print(df.groupby("format").agg(files=("path", "nunique"), rows=("n_rows", "sum")).to_string())
        print("\n=== by handle ===")
        print(df.groupby("handle").agg(files=("path", "nunique"), rows=("n_rows", "sum")).to_string())
        errs = df[df["error"] != ""]
        if len(errs):
            print(f"\n=== {len(errs)} error rows ===")
            for _, r in errs.head(10).iterrows():
                print(f"  {r['path']}: {r['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
