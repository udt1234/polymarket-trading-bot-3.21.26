from fastapi import APIRouter
from api.dependencies import get_supabase

router = APIRouter()

VALID_LOG_TYPES = {"decision", "execution", "system", "risk"}


@router.get("/")
async def get_logs(
    log_type: str | None = None,
    severity: str | None = None,
    module_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
):
    sb = get_supabase()
    query = sb.table("logs").select("*", count="exact")

    if log_type and log_type in VALID_LOG_TYPES:
        query = query.eq("log_type", log_type)
    if severity:
        query = query.eq("severity", severity)
    if module_id:
        query = query.eq("module_id", module_id)
    if search:
        query = query.ilike("message", f"%{search}%")

    res = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"data": res.data, "total": res.count}
