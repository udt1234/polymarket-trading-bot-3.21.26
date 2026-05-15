"""Refresh whale_snapshots for resolved auctions. Idempotent.

Phase 2 of WHALE_BRACKET_CARDS_SPEC.md. Designed to run nightly via Railway
cron (3 AM ET = 8 AM UTC) and also serve as the one-time backfill — the
"not-yet-snapshotted" query covers both modes.

Usage:
    python scripts/refresh_whale_snapshots.py [--dry-run] [--handle HANDLE]
                                              [--max-per-handle N]

Cron command (Railway dashboard): python scripts/refresh_whale_snapshots.py
Default: process up to 20 unsnapshotted auctions per handle per run.
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_env() -> None:
    if os.environ.get("SUPABASE_URL"):
        return
    # Look for .env in the worktree root, then walk up — worktrees mirror the
    # main repo's .env via the parent project, but only the main repo has it.
    candidates = [REPO_ROOT / ".env"]
    parent = REPO_ROOT
    for _ in range(4):
        parent = parent.parent
        candidates.append(parent / ".env")
    for env_file in candidates:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k and v and k not in os.environ:
                    os.environ[k] = v.strip()
            return


_load_env()

# Imports must come AFTER env load so api.dependencies sees the keys.
from api.services.whale_snapshot import (  # noqa: E402
    build_snapshot,
    list_not_yet_snapshotted,
    upsert_snapshot,
)
from api.services.profiles import get_active_profile  # noqa: E402


def _resolve_bot_wallet() -> str | None:
    """The bot's proxy wallet — the address that appears in proxyWallet of
    every fill. Tries the active profile first, then POLYMARKET_WALLET_ADDRESS
    env var (the deployed bot uses env-only creds and has no profile row)."""
    try:
        prof = get_active_profile()
        addr = (prof or {}).get("wallet_address") or None
        if addr:
            return addr.lower()
    except Exception as exc:
        logging.warning(f"profile lookup failed: {exc}")
    env_addr = os.environ.get("POLYMARKET_WALLET_ADDRESS")
    return env_addr.lower() if env_addr else None


def _to_dt(s: str | datetime) -> datetime:
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def _process_handle(
    handle: str,
    max_per_handle: int,
    bot_wallet: str | None,
    dry_run: bool,
) -> tuple[int, int]:
    """Returns (succeeded, skipped)."""
    rows = list_not_yet_snapshotted(handle=handle, limit=max_per_handle)
    if not rows:
        print(f"  [{handle}] nothing to snapshot.")
        return (0, 0)
    print(f"  [{handle}] processing {len(rows)} auctions...")
    succeeded = skipped = 0
    for r in rows:
        slug = r["auction_slug"]
        try:
            row = await build_snapshot(
                handle=handle,
                auction_slug=slug,
                auction_start=_to_dt(r["start_date"]),
                auction_end=_to_dt(r["end_date"]),
                bot_wallet=bot_wallet,
                final_value=r.get("final_value"),
                winning_bracket=r.get("winning_bracket"),
            )
        except Exception as exc:
            print(f"    SKIP {slug}: build_snapshot failed: {exc}")
            skipped += 1
            continue
        if row is None:
            print(f"    SKIP {slug}: no markets/trades")
            skipped += 1
            continue
        if dry_run:
            print(
                f"    DRY {slug}: would upsert "
                f"({len(row['top_wallets'])} top wallets, "
                f"{len(row['market_universe'])} markets)"
            )
            succeeded += 1
        else:
            try:
                upsert_snapshot(row)
                print(f"    OK  {slug} (top={len(row['top_wallets'])})")
                succeeded += 1
            except Exception as exc:
                print(f"    SKIP {slug}: upsert failed: {exc}")
                skipped += 1
    return (succeeded, skipped)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handle", help="Restrict to one handle (else all known)")
    parser.add_argument(
        "--max-per-handle", type=int, default=20,
        help="Max auctions to process per handle per run (default 20)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    bot_wallet = _resolve_bot_wallet()
    print(f"bot_wallet = {bot_wallet or 'unknown'}")

    handles = [args.handle] if args.handle else _discover_handles()
    if not handles:
        print("No handles configured / supplied. Exiting.")
        return 0

    total_ok = total_skip = 0
    for h in handles:
        ok, sk = await _process_handle(h, args.max_per_handle, bot_wallet, args.dry_run)
        total_ok += ok
        total_skip += sk

    print(f"\nDone. succeeded={total_ok} skipped={total_skip}")
    return 0


def _discover_handles() -> list[str]:
    """Distinct handles present in auction_archive."""
    try:
        from api.dependencies import get_supabase
        sb = get_supabase()
        # Limit query to recent rows for speed; we only care about active modules.
        res = sb.table("auction_archive").select("handle").limit(2000).execute()
        return sorted({(r.get("handle") or "").strip() for r in (res.data or []) if r.get("handle")})
    except Exception as exc:
        logging.error(f"handle discovery failed: {exc}")
        return []


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
