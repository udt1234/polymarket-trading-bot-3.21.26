from fastapi import APIRouter
from api.dependencies import get_supabase

router = APIRouter()


@router.get("/")
async def list_trades(limit: int = 50, offset: int = 0, module_id: str | None = None):
    sb = get_supabase()
    query = sb.table("trades").select("*", count="exact")
    if module_id:
        query = query.eq("module_id", module_id)
    res = query.order("executed_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"data": res.data, "total": res.count}


@router.get("/orders")
async def list_orders(status: str | None = None, limit: int = 50):
    sb = get_supabase()
    query = sb.table("orders").select("*")
    if status:
        query = query.eq("status", status)
    res = query.order("created_at", desc=True).limit(limit).execute()
    return res.data
