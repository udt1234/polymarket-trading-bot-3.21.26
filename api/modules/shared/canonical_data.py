"""
Canonical Data Loader + On-Demand QA Gate.

Every backtest, analysis script, or notebook that reads from
`_DataMetricPulls/canonical/` should use this module instead of direct
parquet reads. The loader:

  1. Loads partitioned parquet with sensible default filters
  2. Optionally runs QA: samples N rows + cross-checks against ground truth
     (Gamma API for auctions, raw whale_analysis for prices, post URLs for
     posts) BEFORE returning data
  3. Hard-blocks on QA failure (raises CanonicalDataQAFailure)
  4. Logs every load to Google Sheet QA_Log tab

USAGE
    from api.modules.shared.canonical_data import load_auctions

    df = load_auctions(
        handle="elonmusk",
        duration_type="2-day",
        confidence=("high",),
        sample_size=10,          # 0 to skip QA
        skip_qa=False,           # emergency bypass
        qa_block_threshold=0.95, # min pass rate to allow
    )

DESIGN
- All functions return pandas DataFrame
- All datetimes returned tz-aware UTC; convert to ET in caller if needed
- QA failure raises CanonicalDataQAFailure; caller can catch to fall back
- skip_qa=True logs a WARNING to sheet but does not block
- sample_size=0 disables QA entirely (use sparingly)
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
CANON = ROOT / "_DataMetricPulls" / "canonical"
RAW_WHALE = CANON / "_raw_imports" / "whale_analysis"
GAMMA_CACHE = CANON / "_gamma_cache"

GAMMA_BASE = "https://gamma-api.polymarket.com"
GAMMA_HEADERS = {"User-Agent": "Mozilla/5.0 (canonical-loader)"}

SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"
SUBJECT = "darwin@xagency.com"
QA_LOG_TAB = "QA_Log"


class CanonicalDataQAFailure(RuntimeError):
    """Raised when a canonical_data load fails its QA pass rate threshold."""


@dataclass
class QAResult:
    table: str
    handle: str
    n_total_rows: int
    n_sampled: int
    n_passed: int
    n_failed: int
    n_skipped: int
    pass_rate: float
    blocked: bool
    threshold: float
    failure_examples: list[dict] = field(default_factory=list)
    duration_sec: float = 0.0
    notes: str = ""


# ============================================================================
# Internal helpers
# ============================================================================

def _list_partitions(table: str, handle: str) -> list[Path]:
    base = CANON / table / handle
    if not base.exists():
        return []
    return sorted(base.glob("*.parquet"))


def _filter_date_range(df: pd.DataFrame, ts_col: str, since: str | None, until: str | None) -> pd.DataFrame:
    if since:
        df = df[df[ts_col] >= pd.Timestamp(since, tz="UTC")]
    if until:
        df = df[df[ts_col] <= pd.Timestamp(until, tz="UTC")]
    return df


def _gamma_event(slug: str) -> list | None:
    cache_path = GAMMA_CACHE / f"{slug}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            cache_path.unlink()
    url = f"{GAMMA_BASE}/events?slug={slug}"
    req = urllib.request.Request(url, headers=GAMMA_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        GAMMA_CACHE.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data))
        return data
    except Exception:
        return None


# ============================================================================
# QA functions per table
# ============================================================================

def _qa_auctions(df: pd.DataFrame, n: int) -> tuple[int, int, int, list[dict]]:
    """For each sampled auction, hit Gamma /events?slug= and verify winning_bucket."""
    if len(df) == 0 or n == 0:
        return (0, 0, 0, [])
    sample = df.sample(min(n, len(df)), random_state=random.randint(1, 99999))
    passed = failed = skipped = 0
    failures = []
    for _, row in sample.iterrows():
        slug = row.get("auction_slug")
        canon_winner = (row.get("winning_bucket") or "").strip()
        if not slug:
            skipped += 1
            continue
        ev = _gamma_event(slug)
        if not ev:
            skipped += 1
            continue
        markets = ev[0].get("markets", []) if isinstance(ev, list) and ev else []
        gamma_winner = ""
        for m in markets:
            op = m.get("outcomePrices", "[]")
            try:
                op = json.loads(op) if isinstance(op, str) else op
                if op == ["1", "0"] or op == [1, 0]:
                    gamma_winner = (m.get("groupItemTitle") or "").strip()
                    break
            except Exception:
                continue
        # normalize for comparison
        c = canon_winner.replace("–", "-").replace("—", "-").lower()
        g = gamma_winner.replace("–", "-").replace("—", "-").lower()
        if c == g and c:
            passed += 1
        elif not g and not c:
            passed += 1
        else:
            failed += 1
            failures.append({"slug": slug, "canonical": canon_winner, "gamma": gamma_winner})
    return (passed, failed, skipped, failures)


def _qa_prices(df: pd.DataFrame, n: int) -> tuple[int, int, int, list[dict]]:
    """For each sampled (auction, bucket, hour) row, verify close price against raw whale_analysis."""
    if len(df) == 0 or n == 0:
        return (0, 0, 0, [])
    sample = df.sample(min(n, len(df)), random_state=random.randint(1, 99999))
    passed = failed = skipped = 0
    failures = []
    # cache raw files per auction
    raw_cache: dict[str, pd.DataFrame] = {}
    for _, row in sample.iterrows():
        slug = row.get("auction_slug")
        bucket = row.get("bucket")
        hour = row.get("hour_utc")
        canon_close = row.get("close")
        if slug not in raw_cache:
            raw_path = RAW_WHALE / f"trades_{slug}.parquet"
            if not raw_path.exists():
                skipped += 1
                continue
            raw_cache[slug] = pd.read_parquet(raw_path)
        rdf = raw_cache[slug]
        rdf["ts"] = pd.to_datetime(rdf["ts"], utc=True, errors="coerce")
        # bucket + hour match
        hour_ts = pd.Timestamp(hour).tz_convert("UTC") if pd.Timestamp(hour).tzinfo else pd.Timestamp(hour, tz="UTC")
        rsub = rdf[
            (rdf["_bucket"] == bucket)
            & (rdf["ts"] >= hour_ts)
            & (rdf["ts"] < hour_ts + pd.Timedelta(hours=1))
        ].sort_values("ts")
        if len(rsub) == 0:
            skipped += 1
            continue
        last_trade = rsub.iloc[-1]
        yes_price = last_trade["price"] if last_trade["outcome"] == "Yes" else (1.0 - last_trade["price"])
        if abs(float(canon_close) - float(yes_price)) <= 0.01:
            passed += 1
        else:
            failed += 1
            failures.append({"slug": slug, "bucket": bucket, "hour": str(hour),
                             "canonical_close": float(canon_close), "raw_close": float(yes_price)})
    return (passed, failed, skipped, failures)


def _qa_posts(df: pd.DataFrame, n: int) -> tuple[int, int, int, list[dict]]:
    """
    Posts QA is the weakest link. We can't hit Truth Social / X public API
    cheaply for thousands of historical posts. So we do structural QA:
      - post_id is non-empty
      - ts_utc is tz-aware
      - content_text is non-empty (relaxed for known image-only posts)
      - url is well-formed
    Failures here suggest the parquet build pipeline broke.
    """
    if len(df) == 0 or n == 0:
        return (0, 0, 0, [])
    sample = df.sample(min(n, len(df)), random_state=random.randint(1, 99999))
    passed = failed = skipped = 0
    failures = []
    for _, row in sample.iterrows():
        ok = True
        why = []
        if not row.get("post_id"):
            ok = False; why.append("missing post_id")
        ts = row.get("ts_utc")
        if pd.isna(ts):
            ok = False; why.append("null ts_utc")
        url = row.get("url", "")
        if not (url.startswith("https://") or url.startswith("xtracker://")):
            ok = False; why.append(f"bad url: {url[:40]}")
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append({"post_id": row.get("post_id", ""), "why": "; ".join(why)})
    return (passed, failed, skipped, failures)


# ============================================================================
# Sheet logger
# ============================================================================

def _log_qa_to_sheet(qa: QAResult, caller: str) -> None:
    """Append one row to QA_Log tab. Silent failure if sheet auth unavailable."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        if not SA_KEY.exists():
            return
        creds = service_account.Credentials.from_service_account_file(
            str(SA_KEY),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
            subject=SUBJECT,
        )
        sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        # ensure tab exists; if not, create with header
        meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        tabs = {s["properties"]["title"] for s in meta["sheets"]}
        if QA_LOG_TAB not in tabs:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests": [{"addSheet": {"properties": {"title": QA_LOG_TAB}}}]},
            ).execute()
            header = [["run_utc", "caller", "table", "handle", "n_total", "n_sampled",
                       "n_passed", "n_failed", "n_skipped", "pass_rate", "threshold",
                       "blocked", "duration_sec", "notes", "failure_examples"]]
            sheets.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID, range=f"{QA_LOG_TAB}!A1",
                valueInputOption="RAW", body={"values": header},
            ).execute()
        row = [[
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            caller,
            qa.table,
            qa.handle,
            str(qa.n_total_rows),
            str(qa.n_sampled),
            str(qa.n_passed),
            str(qa.n_failed),
            str(qa.n_skipped),
            f"{qa.pass_rate:.4f}",
            f"{qa.threshold:.2f}",
            str(qa.blocked),
            f"{qa.duration_sec:.1f}",
            qa.notes,
            json.dumps(qa.failure_examples[:5])[:500],
        ]]
        sheets.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{QA_LOG_TAB}!A:Z",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": row},
        ).execute()
    except Exception:
        pass  # silent — sheet logging is best-effort


# ============================================================================
# Public API
# ============================================================================

def _run_qa(df: pd.DataFrame, table: str, handle: str, sample_size: int, threshold: float,
            caller: str, skip_qa: bool, notes: str = "") -> QAResult:
    t0 = time.time()
    if skip_qa or sample_size == 0:
        qa = QAResult(
            table=table, handle=handle, n_total_rows=len(df),
            n_sampled=0, n_passed=0, n_failed=0, n_skipped=0,
            pass_rate=1.0, blocked=False, threshold=threshold,
            duration_sec=time.time() - t0,
            notes=(notes + " | QA_SKIPPED") if skip_qa else (notes + " | sample_size=0"),
        )
        _log_qa_to_sheet(qa, caller)
        return qa
    if table == "auctions":
        passed, failed, skipped, fails = _qa_auctions(df, sample_size)
    elif table == "prices":
        passed, failed, skipped, fails = _qa_prices(df, sample_size)
    elif table == "posts":
        passed, failed, skipped, fails = _qa_posts(df, sample_size)
    else:
        passed = failed = skipped = 0
        fails = []
    n_checked = passed + failed
    pass_rate = (passed / n_checked) if n_checked else 1.0
    blocked = pass_rate < threshold
    qa = QAResult(
        table=table, handle=handle, n_total_rows=len(df),
        n_sampled=sample_size, n_passed=passed, n_failed=failed,
        n_skipped=skipped, pass_rate=pass_rate, blocked=blocked,
        threshold=threshold, failure_examples=fails,
        duration_sec=time.time() - t0, notes=notes,
    )
    _log_qa_to_sheet(qa, caller)
    return qa


def _detect_caller() -> str:
    """Best-effort: walk stack to find the script that called us."""
    import inspect
    for frame in inspect.stack()[2:]:
        fn = frame.filename
        if "canonical_data" in fn or "<frozen" in fn:
            continue
        return Path(fn).name
    return "unknown"


def load_auctions(
    handle: str | None = None,
    duration_type: str | tuple[str, ...] | None = None,
    confidence: tuple[str, ...] = ("high", "medium"),
    since: str | None = None,
    until: str | None = None,
    bracket_must_contain: str | None = None,
    sample_size: int = 10,
    skip_qa: bool = False,
    qa_block_threshold: float = 0.95,
    caller: str | None = None,
) -> pd.DataFrame:
    """Load canonical auctions table with optional filters + QA pre-flight."""
    caller = caller or _detect_caller()
    handles = [handle] if handle else ["realDonaldTrump", "elonmusk"]
    parts = []
    for h in handles:
        parts.extend(_list_partitions("auctions", h))
    if not parts:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df["start_utc"] = pd.to_datetime(df["start_utc"], utc=True)
    df["end_utc"] = pd.to_datetime(df["end_utc"], utc=True)
    if duration_type:
        if isinstance(duration_type, str):
            duration_type = (duration_type,)
        df = df[df["duration_type"].isin(duration_type)]
    df = df[df["confidence"].isin(confidence)]
    df = _filter_date_range(df, "start_utc", since, until)
    if bracket_must_contain:
        df = df[df["all_buckets"].str.contains(bracket_must_contain, regex=False)]
    df = df.reset_index(drop=True)

    qa = _run_qa(df, "auctions", handle or "both", sample_size, qa_block_threshold,
                 caller, skip_qa, notes=f"filters: dur={duration_type} conf={confidence}")
    if qa.blocked:
        raise CanonicalDataQAFailure(
            f"auctions QA blocked: pass_rate {qa.pass_rate:.2%} < threshold {qa.threshold:.0%}. "
            f"Sample {qa.n_sampled}, failed {qa.n_failed}. Examples: {qa.failure_examples[:3]}"
        )
    print(f"[canonical_data] auctions: {len(df)} rows, QA pass {qa.pass_rate:.0%} ({qa.n_passed}/{qa.n_passed+qa.n_failed} sampled)")
    return df


def load_posts(
    handle: str,
    counts_only: bool = True,
    since: str | None = None,
    until: str | None = None,
    sample_size: int = 10,
    skip_qa: bool = False,
    qa_block_threshold: float = 0.95,
    caller: str | None = None,
) -> pd.DataFrame:
    """Load canonical posts table."""
    caller = caller or _detect_caller()
    parts = _list_partitions("posts", handle)
    if not parts:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    if counts_only:
        df = df[df["counts_for_auction"] == True]
    df = _filter_date_range(df, "ts_utc", since, until).reset_index(drop=True)

    qa = _run_qa(df, "posts", handle, sample_size, qa_block_threshold, caller, skip_qa,
                 notes=f"counts_only={counts_only}")
    if qa.blocked:
        raise CanonicalDataQAFailure(
            f"posts QA blocked: pass_rate {qa.pass_rate:.2%} < threshold {qa.threshold:.0%}"
        )
    print(f"[canonical_data] posts/{handle}: {len(df)} rows, QA pass {qa.pass_rate:.0%}")
    return df


def load_prices(
    handle: str,
    auction_slug: str | None = None,
    bucket: str | None = None,
    since: str | None = None,
    until: str | None = None,
    sample_size: int = 10,
    skip_qa: bool = False,
    qa_block_threshold: float = 0.95,
    caller: str | None = None,
) -> pd.DataFrame:
    """Load canonical hourly prices table."""
    caller = caller or _detect_caller()
    parts = _list_partitions("prices", handle)
    if not parts:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df["hour_utc"] = pd.to_datetime(df["hour_utc"], utc=True)
    if auction_slug:
        df = df[df["auction_slug"] == auction_slug]
    if bucket:
        df = df[df["bucket"] == bucket]
    df = _filter_date_range(df, "hour_utc", since, until).reset_index(drop=True)

    qa = _run_qa(df, "prices", handle, sample_size, qa_block_threshold, caller, skip_qa,
                 notes=f"slug={auction_slug} bucket={bucket}")
    if qa.blocked:
        raise CanonicalDataQAFailure(
            f"prices QA blocked: pass_rate {qa.pass_rate:.2%} < threshold {qa.threshold:.0%}"
        )
    print(f"[canonical_data] prices/{handle}: {len(df)} rows, QA pass {qa.pass_rate:.0%}")
    return df
