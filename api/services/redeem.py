"""Redeem resolved (closed) Polymarket positions for USDC.

Redemption is NOT a CLOB/REST operation — there is no Polymarket API endpoint
that pays out a winning position. Once a market resolves, the holder owns
ERC-1155 conditional tokens that must be redeemed on-chain by calling
`redeemPositions` on Polygon:

  - Regular markets   -> ConditionalTokens (CTF) contract
  - Neg-risk markets  -> NegRiskAdapter contract

The Polymarket data-api `/positions` endpoint is the source of truth for WHICH
positions are redeemable (`redeemable: true`) and whether each market is
neg-risk (`negativeRisk: true`). This module reads that, groups by market, and
submits one `redeemPositions` transaction per resolved condition.

Safety:
  - `dry_run=True` is the DEFAULT. Nothing is broadcast unless the caller
    explicitly passes `dry_run=False`.
  - The conditional tokens are held by the wallet that traded. If the EOA
    derived from the private key does not match the position `proxyWallet`
    (i.e. the account is a Polymarket email/Magic proxy or a Gnosis Safe),
    a direct EOA redemption would revert / pay nothing, so we abort with a
    clear message instead of burning gas.
"""

import logging

from api.services.wallet import fetch_wallet_positions

log = logging.getLogger(__name__)

# --- Polygon mainnet (chainId 137) ------------------------------------------
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"        # ConditionalTokens
NEG_RISK_ADAPTER = "0x78769D50Be1763ed1CA0D5E878D93f05aabff29e"   # NegRiskAdapter
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"       # USDC.e collateral
ZERO_BYTES32 = "0x" + "00" * 32
POLYGON_CHAIN_ID = 137
DEFAULT_RPC_URL = "https://polygon-rpc.com"

CTF_REDEEM_ABI = [{
    "constant": False,
    "inputs": [
        {"name": "collateralToken", "type": "address"},
        {"name": "parentCollectionId", "type": "bytes32"},
        {"name": "conditionId", "type": "bytes32"},
        {"name": "indexSets", "type": "uint256[]"},
    ],
    "name": "redeemPositions",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}]

# NegRiskAdapter pays out based on the amount of each outcome token the caller
# holds, so it takes an explicit per-outcome `_amounts` array (6-decimal units).
NEG_RISK_REDEEM_ABI = [{
    "constant": False,
    "inputs": [
        {"name": "_conditionId", "type": "bytes32"},
        {"name": "_amounts", "type": "uint256[]"},
    ],
    "name": "redeemPositions",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}]

USDC_DECIMALS = 6


def _to_bytes32(hex_str: str) -> bytes:
    """Convert a 0x-prefixed hex conditionId into a 32-byte value."""
    raw = bytes.fromhex(hex_str[2:] if hex_str.startswith("0x") else hex_str)
    if len(raw) != 32:
        raise ValueError(f"conditionId is not 32 bytes: {hex_str}")
    return raw


def is_redeemable(position: dict) -> bool:
    """A position is redeemable once Polymarket flags it as such.

    We trust the data-api `redeemable` flag rather than re-deriving resolution
    from price/end-date: the flag is only set true after the on-chain condition
    is actually resolved AND the position still holds redeemable tokens.
    """
    return bool(position.get("redeemable", False)) and float(position.get("size", 0) or 0) > 0


async def find_redeemable_positions(wallet_address: str) -> list[dict]:
    """Return every redeemable (resolved, still-held) position for a wallet."""
    positions = await fetch_wallet_positions(wallet_address, limit=500)
    return [p for p in positions if is_redeemable(p)]


def _group_redeemable(positions: list[dict]) -> list[dict]:
    """Group redeemable positions into one redemption per (condition, neg-risk).

    A binary market has up to two outcome tokens (YES/NO) under one
    conditionId. We accumulate the held size per outcome index so the
    neg-risk path can pass a correct `_amounts` array, and the CTF path can
    redeem every index slot we hold.
    """
    groups: dict[tuple[str, bool], dict] = {}
    for p in positions:
        condition_id = p.get("conditionId") or p.get("condition_id")
        if not condition_id:
            log.warning(f"Skipping redeemable position with no conditionId: {p.get('title')}")
            continue
        neg_risk = bool(p.get("negativeRisk", False))
        key = (condition_id, neg_risk)
        g = groups.setdefault(key, {
            "condition_id": condition_id,
            "neg_risk": neg_risk,
            "title": p.get("title", ""),
            "outcomes": {},          # outcome_index -> size (shares)
            "total_value": 0.0,
        })
        idx = int(p.get("outcomeIndex", 0) or 0)
        size = float(p.get("size", 0) or 0)
        g["outcomes"][idx] = g["outcomes"].get(idx, 0.0) + size
        # currentValue is what the position is worth post-resolution (≈ payout).
        g["total_value"] += float(p.get("currentValue", 0) or 0)
    return list(groups.values())


def _amounts_array(outcomes: dict[int, float]) -> list[int]:
    """Build the neg-risk `_amounts` array (6-decimal units) indexed by outcome.

    NegRiskAdapter markets are binary (YES/NO) under one conditionId, so the
    array must carry an entry per outcome even when we only hold the winning
    side — hence the minimum length of 2 with unheld slots zero-filled.
    """
    if not outcomes:
        return []
    n = max(2, max(outcomes) + 1)
    return [int(round(outcomes.get(i, 0.0) * (10 ** USDC_DECIMALS))) for i in range(n)]


def _index_sets(outcomes: dict[int, float]) -> list[int]:
    """CTF index sets for the outcome slots we hold (1-based bitmask per slot)."""
    return [1 << i for i in sorted(outcomes)]


def _resolve_profile(profile: dict | None) -> dict:
    if profile is not None:
        return profile
    from api.services.profiles import get_active_profile
    return get_active_profile()


async def redeem_all_positions(
    profile: dict | None = None,
    dry_run: bool = True,
    rpc_url: str | None = None,
) -> dict:
    """Redeem every resolved position held by the active (or given) profile.

    Args:
        profile: profile dict with `polymarket_private_key` + `wallet_address`.
                 Defaults to the active profile.
        dry_run: when True (default) nothing is broadcast — returns the plan.
        rpc_url: Polygon RPC endpoint. Falls back to the profile's
                 `polygon_rpc_url`, then settings, then a public default.

    Returns a summary dict: planned/redeemed groups, tx hashes, est. payout.
    """
    profile = _resolve_profile(profile)
    private_key = profile.get("polymarket_private_key", "")
    wallet_address = profile.get("wallet_address", "")

    if not private_key:
        raise ValueError("No polymarket_private_key in profile — cannot sign redemption")

    from web3 import Web3
    from eth_account import Account

    account = Account.from_key(private_key)
    eoa = account.address
    # If the profile didn't store a wallet_address, the EOA is the only wallet
    # we can act on — use it for the positions lookup.
    lookup_wallet = wallet_address or eoa

    redeemable = await find_redeemable_positions(lookup_wallet)
    groups = _group_redeemable(redeemable)

    summary = {
        "wallet": lookup_wallet,
        "eoa": eoa,
        "dry_run": dry_run,
        "redeemable_positions": len(redeemable),
        "redeemable_markets": len(groups),
        "estimated_payout_usdc": round(sum(g["total_value"] for g in groups), 4),
        "results": [],
    }

    if not groups:
        log.info(f"No redeemable positions for {lookup_wallet}")
        return summary

    # Tokens are held by the wallet that traded. If that wallet is a Polymarket
    # proxy / Safe (≠ our EOA), a direct EOA redemption pays nothing — abort.
    if wallet_address and Web3.to_checksum_address(wallet_address) != Web3.to_checksum_address(eoa):
        summary["error"] = (
            f"Position wallet ({wallet_address}) is not the signing EOA ({eoa}). "
            "This looks like a Polymarket proxy/Safe wallet — direct on-chain "
            "redemption from the EOA would not pay out. Redeem via the proxy "
            "relayer instead."
        )
        log.error(summary["error"])
        return summary

    if dry_run:
        for g in groups:
            summary["results"].append({
                "condition_id": g["condition_id"],
                "title": g["title"],
                "neg_risk": g["neg_risk"],
                "outcomes": g["outcomes"],
                "estimated_payout_usdc": round(g["total_value"], 4),
                "status": "planned",
            })
        log.info(
            f"DRY RUN: {len(groups)} redeemable markets "
            f"(~${summary['estimated_payout_usdc']:.2f}) for {lookup_wallet}"
        )
        return summary

    rpc = rpc_url or profile.get("polygon_rpc_url") or _settings_rpc()
    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise ConnectionError(f"Could not connect to Polygon RPC: {rpc}")

    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_REDEEM_ABI)
    neg = w3.eth.contract(address=Web3.to_checksum_address(NEG_RISK_ADAPTER), abi=NEG_RISK_REDEEM_ABI)
    nonce = w3.eth.get_transaction_count(eoa)

    for g in groups:
        cid = g["condition_id"]
        try:
            condition_bytes = _to_bytes32(cid)
            if g["neg_risk"]:
                fn = neg.functions.redeemPositions(condition_bytes, _amounts_array(g["outcomes"]))
            else:
                fn = ctf.functions.redeemPositions(
                    Web3.to_checksum_address(USDC_ADDRESS),
                    ZERO_BYTES32,
                    condition_bytes,
                    _index_sets(g["outcomes"]),
                )

            tx = fn.build_transaction({
                "from": eoa,
                "nonce": nonce,
                "chainId": POLYGON_CHAIN_ID,
                "gas": 250_000,
                "maxFeePerGas": w3.to_wei(200, "gwei"),
                "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
            })
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            ok = receipt.get("status") == 1
            nonce += 1

            summary["results"].append({
                "condition_id": cid,
                "title": g["title"],
                "neg_risk": g["neg_risk"],
                "estimated_payout_usdc": round(g["total_value"], 4),
                "tx_hash": tx_hash.hex(),
                "status": "redeemed" if ok else "reverted",
            })
            log.info(f"Redeem {'OK' if ok else 'REVERTED'} {g['title'][:40]} tx={tx_hash.hex()}")
        except Exception as e:
            summary["results"].append({
                "condition_id": cid,
                "title": g["title"],
                "neg_risk": g["neg_risk"],
                "status": "error",
                "error": str(e),
            })
            log.error(f"Redeem failed for {cid}: {e}")

    summary["redeemed"] = sum(1 for r in summary["results"] if r.get("status") == "redeemed")
    return summary


def _settings_rpc() -> str:
    try:
        from api.config import get_settings
        return getattr(get_settings(), "polygon_rpc_url", "") or DEFAULT_RPC_URL
    except Exception:
        return DEFAULT_RPC_URL
