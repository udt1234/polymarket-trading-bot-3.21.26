"""External process-level kill switch (BUILD_SPEC G4). CLI ONLY - there is
deliberately NO HTTP endpoint for this (the old /api/engine/stop lesson:
endpoint names lie and get called casually).

  python scripts/kill_switch.py --pause      # stop new entries (exits keep firing)
  python scripts/kill_switch.py --cancel-all # cancel every resting CLOB order
  python scripts/kill_switch.py --resume     # clear the pause

--cancel-all NEVER liquidates positions. Closing positions stays a human
decision made bracket-by-bracket.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.polymarket_proxy import install_httpx_proxy_patch

install_httpx_proxy_patch()

from api.dependencies import get_supabase  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--cancel-all", action="store_true")
    args = ap.parse_args()
    sb = get_supabase()
    if args.pause:
        until = datetime.now(timezone.utc) + timedelta(days=3650)
        sb.table("settings").upsert({"key": "circuit_breaker", "value": {
            "consecutive_losses": 0, "cooldown_until": until.isoformat(),
            "trips": -1, "manual": True}}).execute()
        print(f"PAUSED: entries blocked until {until.date()} (exits still run)")
    if args.resume:
        sb.table("settings").upsert({"key": "circuit_breaker", "value": {
            "consecutive_losses": 0, "cooldown_until": "", "trips": 0}}).execute()
        print("RESUMED: breaker cleared")
    if args.cancel_all:
        from api.services import clob
        print("cancelling ALL resting CLOB orders...")
        print(clob.cancel_all())
    if not any([args.pause, args.resume, args.cancel_all]):
        ap.print_help()


if __name__ == "__main__":
    main()
