from fastapi import APIRouter, Query
from datetime import datetime, timezone
from api.dependencies import get_supabase

router = APIRouter()


@router.get("/handles")
async def list_handles():
    return [
        {"handle": "realDonaldTrump", "label": "Trump (Truth Social)"},
        {"handle": "elonmusk", "label": "Elon (X / Twitter)"},
    ]


@router.get("/sources")
async def list_sources(handle: str | None = None):
    sources = ["xtracker"]
    if handle == "realDonaldTrump":
        sources.append("truthsocial_direct")
    elif handle == "elonmusk":
        sources.append("ifttt_x")
    return sources


@router.get("/posts")
async def get_posts(
    handle: str = "realDonaldTrump",
    start: str | None = None,
    end: str | None = None,
    hour: int | None = Query(default=None, ge=0, le=23),
    dow: int | None = Query(default=None, ge=0, le=6),
    limit: int = Query(default=200, le=2000),
    offset: int = 0,
):
    sb = get_supabase()
    if handle == "realDonaldTrump":
        q = sb.table("truth_social_posts").select("id,handle,created_at,is_reply,is_reblog", count="exact").eq("handle", handle)
    elif handle == "elonmusk":
        q = sb.table("elon_tweets").select("id,handle,created_at,is_reply,is_retweet,url,text", count="exact").eq("handle", "elonmusk")
    else:
        return {"data": [], "total": 0, "note": f"No raw post archive for {handle}"}

    if start:
        q = q.gte("created_at", start)
    if end:
        q = q.lte("created_at", end)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    rows = res.data or []
    if hour is not None or dow is not None:
        filtered = []
        for r in rows:
            dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            if hour is not None and dt.hour != hour:
                continue
            if dow is not None and dt.weekday() != dow:
                continue
            filtered.append(r)
        rows = filtered
    return {"data": rows, "total": res.count or 0}


@router.get("/post-counts")
async def get_post_counts(
    handle: str = "realDonaldTrump",
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(default=500, le=5000),
):
    sb = get_supabase()
    mod_name_map = {"realDonaldTrump": "Truth Social Posts", "elonmusk": "Elon Tweets"}
    mod_name = mod_name_map.get(handle)
    if not mod_name:
        return []
    mod = sb.table("modules").select("id").ilike("name", mod_name).execute()
    if not mod.data:
        return []
    module_id = mod.data[0]["id"]
    q = sb.table("post_count_snapshots").select("captured_at,source,count,latest_post_at,window_start,window_end").eq("module_id", module_id)
    if source:
        q = q.eq("source", source)
    if start:
        q = q.gte("captured_at", start)
    if end:
        q = q.lte("captured_at", end)
    res = q.order("captured_at", desc=True).limit(limit).execute()
    return res.data or []


@router.get("/prices")
async def get_prices(
    handle: str = "realDonaldTrump",
    bracket: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(default=500, le=5000),
):
    sb = get_supabase()
    mod_name_map = {"realDonaldTrump": "Truth Social Posts", "elonmusk": "Elon Tweets"}
    mod_name = mod_name_map.get(handle)
    if not mod_name:
        return []
    mod = sb.table("modules").select("id").ilike("name", mod_name).execute()
    if not mod.data:
        return []
    module_id = mod.data[0]["id"]
    q = sb.table("price_snapshots").select("snapshot_hour,bracket,price,volume,dow,hour_of_day").eq("module_id", module_id)
    if bracket:
        q = q.eq("bracket", bracket)
    if start:
        q = q.gte("snapshot_hour", start)
    if end:
        q = q.lte("snapshot_hour", end)
    res = q.order("snapshot_hour", desc=True).limit(limit).execute()
    return res.data or []


@router.get("/brackets")
async def list_brackets(handle: str = "realDonaldTrump"):
    sb = get_supabase()
    mod_name_map = {"realDonaldTrump": "Truth Social Posts", "elonmusk": "Elon Tweets"}
    mod_name = mod_name_map.get(handle)
    if not mod_name:
        return []
    mod = sb.table("modules").select("id").ilike("name", mod_name).execute()
    if not mod.data:
        return []
    module_id = mod.data[0]["id"]
    res = sb.table("price_snapshots").select("bracket").eq("module_id", module_id).execute()
    brackets = sorted(set(r["bracket"] for r in (res.data or [])))
    return brackets


@router.get("/coverage")
async def data_coverage(handle: str = "realDonaldTrump"):
    sb = get_supabase()
    out = {"handle": handle}

    mod_name_map = {"realDonaldTrump": "Truth Social Posts", "elonmusk": "Elon Tweets"}
    mod_name = mod_name_map.get(handle)
    module_id = None
    if mod_name:
        mod = sb.table("modules").select("id").ilike("name", mod_name).execute()
        if mod.data:
            module_id = mod.data[0]["id"]

    if handle == "realDonaldTrump":
        res = sb.table("truth_social_posts").select("created_at", count="exact").eq("handle", handle).order("created_at").limit(1).execute()
        oldest = res.data[0]["created_at"] if res.data else None
        res2 = sb.table("truth_social_posts").select("created_at").eq("handle", handle).order("created_at", desc=True).limit(1).execute()
        newest = res2.data[0]["created_at"] if res2.data else None
        out["raw_posts"] = {"count": res.count or 0, "oldest": oldest, "newest": newest}

        bf = sb.table("backfill_progress").select("*").eq("handle", handle).execute()
        out["backfill"] = bf.data[0] if bf.data else None

    if handle == "elonmusk":
        try:
            res = sb.table("elon_tweets").select("created_at", count="exact").order("created_at").limit(1).execute()
            oldest = res.data[0]["created_at"] if res.data else None
            res2 = sb.table("elon_tweets").select("created_at").order("created_at", desc=True).limit(1).execute()
            newest = res2.data[0]["created_at"] if res2.data else None
            out["raw_posts"] = {"count": res.count or 0, "oldest": oldest, "newest": newest}
        except Exception:
            out["raw_posts"] = {"count": 0, "oldest": None, "newest": None, "note": "elon_tweets table not yet migrated"}

    if module_id:
        for src in ["xtracker", "truthsocial_direct"]:
            r = sb.table("post_count_snapshots").select("captured_at", count="exact").eq("module_id", module_id).eq("source", src).order("captured_at").limit(1).execute()
            if (r.count or 0) > 0:
                r2 = sb.table("post_count_snapshots").select("captured_at").eq("module_id", module_id).eq("source", src).order("captured_at", desc=True).limit(1).execute()
                out[f"counts_{src}"] = {
                    "count": r.count,
                    "oldest": r.data[0]["captured_at"] if r.data else None,
                    "newest": r2.data[0]["captured_at"] if r2.data else None,
                }

        rp = sb.table("price_snapshots").select("snapshot_hour", count="exact").eq("module_id", module_id).order("snapshot_hour").limit(1).execute()
        if (rp.count or 0) > 0:
            rp2 = sb.table("price_snapshots").select("snapshot_hour").eq("module_id", module_id).order("snapshot_hour", desc=True).limit(1).execute()
            distinct = sb.table("price_snapshots").select("bracket").eq("module_id", module_id).execute()
            brackets = len(set(r["bracket"] for r in (distinct.data or [])))
            out["prices"] = {
                "count": rp.count,
                "brackets": brackets,
                "oldest": rp.data[0]["snapshot_hour"] if rp.data else None,
                "newest": rp2.data[0]["snapshot_hour"] if rp2.data else None,
            }

    return out
