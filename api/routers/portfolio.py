from fastapi import APIRouter
from api.dependencies import get_supabase

router = APIRouter()


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
