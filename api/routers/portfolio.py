from fastapi import APIRouter
from pydantic import BaseModel
from api.dependencies import get_supabase

router = APIRouter()


class RedeemRequest(BaseModel):
    # Default dry_run=True: nothing is broadcast on-chain unless explicitly
    # set to False. Redemption spends gas and submits real Polygon txs.
    dry_run: bool = True
    profile_name: str | None = None


@router.get("/positions")
async def get_positions(status: str = "open", module_id: str | None = None):
    sb = get_supabase()
    query = sb.table("positions").select("*")
    if status != "all":
        query = query.eq("status", status)
    if module_id:
        query = query.eq("module_id", module_id)
    res = query.order("opened_at", desc=True).execute()
    return res.data


@router.get("/exposure")
async def get_exposure(module_id: str | None = None):
    sb = get_supabase()
    query = sb.table("positions").select("*").eq("status", "open")
    if module_id:
        query = query.eq("module_id", module_id)
    positions = query.execute()

    by_module = {}
    total_exposure = 0.0
    total_unrealized = 0.0
    for p in positions.data:
        module = p.get("module_id", "unknown")
        size = abs(p.get("size", 0) * p.get("avg_price", 0))
        by_module.setdefault(module, {"exposure": 0.0, "unrealized_pnl": 0.0, "count": 0})
        by_module[module]["exposure"] += size
        by_module[module]["unrealized_pnl"] += p.get("unrealized_pnl", 0) or 0
        by_module[module]["count"] += 1
        total_exposure += size
        total_unrealized += p.get("unrealized_pnl", 0) or 0

    return {
        "total_exposure": total_exposure,
        "total_unrealized_pnl": total_unrealized,
        "by_module": by_module,
        "position_count": len(positions.data),
    }


@router.get("/pnl")
async def get_pnl(days: int = 30):
    sb = get_supabase()
    rows = sb.table("daily_pnl").select("*").order("date", desc=True).limit(days).execute()
    return list(reversed(rows.data))


@router.get("/redeemable")
async def get_redeemable(profile_name: str | None = None):
    """List resolved (closed) positions that can be redeemed on-chain for USDC."""
    from api.services.redeem import find_redeemable_positions
    from api.services.profiles import get_active_profile, list_profiles

    if profile_name:
        profile = next((p for p in list_profiles() if p.get("name") == profile_name), None)
        if not profile:
            return {"error": f"Profile '{profile_name}' not found", "positions": []}
    else:
        profile = get_active_profile()

    wallet = profile.get("wallet_address", "")
    if not wallet and profile.get("polymarket_private_key"):
        from eth_account import Account
        wallet = Account.from_key(profile["polymarket_private_key"]).address
    if not wallet:
        return {"error": "No wallet_address configured for this profile", "positions": []}

    positions = await find_redeemable_positions(wallet)
    return {
        "wallet": wallet,
        "count": len(positions),
        "estimated_payout_usdc": round(
            sum(float(p.get("currentValue", 0) or 0) for p in positions), 4
        ),
        "positions": positions,
    }


@router.post("/redeem")
async def redeem_positions(req: RedeemRequest):
    """Redeem all resolved positions for USDC via on-chain `redeemPositions`.

    Defaults to a dry run (returns the plan, broadcasts nothing). Pass
    `{"dry_run": false}` to actually submit Polygon transactions.
    """
    from api.services.redeem import redeem_all_positions
    from api.services.profiles import list_profiles

    profile = None
    if req.profile_name:
        profile = next((p for p in list_profiles() if p.get("name") == req.profile_name), None)
        if not profile:
            return {"error": f"Profile '{req.profile_name}' not found"}

    result = await redeem_all_positions(profile=profile, dry_run=req.dry_run)

    if not req.dry_run:
        try:
            sb = get_supabase()
            sb.table("audit_log").insert({
                "action": "redeem_positions",
                "actor": "user",
                "resource_type": "wallet",
                "resource_id": result.get("wallet", ""),
                "details": {
                    "markets": result.get("redeemable_markets", 0),
                    "redeemed": result.get("redeemed", 0),
                    "estimated_payout_usdc": result.get("estimated_payout_usdc", 0),
                },
            }).execute()
        except Exception:
            pass

    return result
