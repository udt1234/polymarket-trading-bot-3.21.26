"""Redeem all resolved (closed) Polymarket positions for USDC.

Redemption is on-chain only — there is no Polymarket REST endpoint that pays
out a winning position. This walks every redeemable position for the active
profile and submits `redeemPositions` on Polygon (CTF for regular markets,
NegRiskAdapter for neg-risk markets).

Usage:
    # Dry run — show what WOULD be redeemed, broadcast nothing (default):
    python scripts/redeem_positions.py

    # Actually broadcast the redemption transactions:
    python scripts/redeem_positions.py --execute

Credentials come from the active profile (Supabase) or .env
(POLYMARKET_PRIVATE_KEY). Set POLYGON_RPC_URL for a private RPC.
"""
import argparse
import asyncio
import json

from api.services.redeem import redeem_all_positions


async def main(execute: bool) -> None:
    result = await redeem_all_positions(dry_run=not execute)
    print(json.dumps(result, indent=2, default=str))

    if not execute and result.get("redeemable_markets"):
        print(
            f"\nDRY RUN — {result['redeemable_markets']} market(s), "
            f"~${result.get('estimated_payout_usdc', 0):.2f} payout. "
            "Re-run with --execute to broadcast."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Redeem resolved Polymarket positions")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Broadcast redemption transactions (default is a dry run)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.execute))
