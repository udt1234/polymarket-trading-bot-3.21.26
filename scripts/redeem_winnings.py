"""Redemption/claim scaffold (BUILD_SPEC Part N). NOT WIRED YET.

Winning conditional tokens must be redeemed ON-CHAIN to become spendable
pUSD; that costs Polygon gas (POL). An unpaid win is NOT a loss - always
reconcile a "failed" redemption against the gas balance first.

Prereqs before this can run (all Sir-gated):
  1. BOT wallet funded: pUSD collateral + POL gas reserve (config
     gas_reserve_pol, default 5 POL).
  2. POLYGON_RPC_URL set (e.g. an Alchemy/Infura Polygon endpoint).
  3. `pip install web3`.

Flow (CTF redeemPositions on 0x4D97DCd97eC945f40cF65F87097ACe5EA0476045):
  for each CLOSED winning position (settle price 1.0, unredeemed):
    - conditionId = positions.market_id
    - collateral = pUSD 0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB
    - call redeemPositions(collateral, bytes32(0), conditionId, [1, 2])
    - confirm receipt, mark positions.metadata.redeemed_tx
Losers (0-dollar) are NEVER redeemed - that only burns gas.

Run --dry-run to list what WOULD be redeemed once prereqs exist.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_supabase  # noqa: E402


def main() -> None:
    sb = get_supabase()
    rows = (sb.table("positions").select("id,market_id,bracket,size,exit_price,realized_pnl")
            .eq("status", "closed").gte("exit_price", 0.999).execute().data) or []
    if not rows:
        print("no redeemable (winning) closed positions")
        return
    print(f"{len(rows)} winning position(s) pending on-chain redemption:")
    for r in rows:
        print(f"  - {r['bracket']} ({r['market_id'][:14]}...) realized {r['realized_pnl']}")
    print("\nDRY RUN ONLY - fund POL gas + set POLYGON_RPC_URL + install web3, "
          "then implement the redeemPositions call per the module docstring.")


if __name__ == "__main__":
    main()
