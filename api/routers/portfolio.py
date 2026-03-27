from fastapi import APIRouter
from api.dependencies import get_supabase

router = APIRouter()


@router.get("/positions")
async def get_positions(status: str = "open"):
    sb = get_supabase()
    query = sb.table("positions").select("*")
    if status != "all":
        query = query.eq("status", status)
    res = query.order("opened_at", desc=True).execute()
    return res.data


@router.get("/exposure")
async def get_exposure():
    sb = get_supabase()
    positions = sb.table("positions").select("*").eq("status", "open").execute()

    by_module = {}
    total_exposure = 0.0
    for p in positions.data:
        module = p.get("module_id", "unknown")
        size = abs(p.get("size", 0) * p.get("avg_price", 0))
        by_module.setdefault(module, 0.0)
        by_module[module] += size
        total_exposure += size

    return {
        "total_exposure": total_exposure,
        "by_module": by_module,
        "position_count": len(positions.data),
    }


@router.get("/pnl")
async def get_pnl(days: int = 30):
    sb = get_supabase()
    rows = sb.table("daily_pnl").select("*").order("date", desc=True).limit(days).execute()
    return list(reversed(rows.data))
