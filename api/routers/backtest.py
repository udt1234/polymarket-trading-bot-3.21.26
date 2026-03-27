import uuid
import logging
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from api.services.backtester import fetch_gamma_events, run_backtest
from api.services.parquet_loader import search_available_data, download_parquet, load_parquet, parquet_to_price_series, HAS_PYARROW
from api.dependencies import get_supabase

router = APIRouter()
log = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    slug: str
    title: str = ""
    clob_token_id: str
    strategy: str = "mean_reversion"
    start_date: str = ""
    end_date: str = ""
    bankroll: float = 1000.0
    kelly_fraction: float = 0.25


@router.get("/search")
async def search_events(q: str = "", limit: int = 20):
    if not q:
        return {"events": [], "total": 0}
    events = await fetch_gamma_events(q, limit=limit)
    return {"events": events, "total": len(events)}


@router.post("/run")
async def run_backtest_endpoint(req: BacktestRequest):
    result = await run_backtest(
        slug=req.slug,
        title=req.title,
        clob_token_id=req.clob_token_id,
        strategy=req.strategy,
        start_date=req.start_date,
        end_date=req.end_date,
        bankroll=req.bankroll,
        kelly_fraction=req.kelly_fraction,
    )

    record_id = str(uuid.uuid4())
    result.id = record_id

    try:
        sb = get_supabase()
        sb.table("backtest_results").insert({
            "id": record_id,
            "slug": result.slug,
            "title": result.title,
            "strategy": result.strategy,
            "bankroll": result.bankroll,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "total_pnl": result.total_pnl,
            "pnl_pct": result.pnl_pct,
            "max_drawdown": result.max_drawdown,
            "sharpe": result.sharpe,
            "sortino": result.sortino,
            "profit_factor": result.profit_factor,
            "avg_edge": result.avg_edge,
            "start_date": result.start_date,
            "end_date": result.end_date,
            "trade_count": result.total_trades,
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        log.warning(f"Failed to save backtest result: {e}")

    return {
        "id": result.id,
        "slug": result.slug,
        "title": result.title,
        "strategy": result.strategy,
        "bankroll": result.bankroll,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": result.win_rate,
        "total_pnl": result.total_pnl,
        "pnl_pct": result.pnl_pct,
        "max_drawdown": result.max_drawdown,
        "sharpe": result.sharpe,
        "sortino": result.sortino,
        "profit_factor": result.profit_factor,
        "avg_edge": result.avg_edge,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "equity_curve": result.equity_curve,
        "daily_pnl": result.daily_pnl,
        "trades": result.trades[:200],
    }


class ParquetDownloadRequest(BaseModel):
    market_slug: str


class ParquetBacktestRequest(BaseModel):
    file_path: str
    strategy: str = "mean_reversion"
    bankroll: float = 1000.0
    kelly_fraction: float = 0.25


@router.get("/parquet/search")
async def search_parquet(q: str = ""):
    if not q:
        return {"markets": [], "total": 0}
    markets = await search_available_data(q)
    return {"markets": markets, "total": len(markets)}


@router.post("/parquet/download")
async def download_parquet_endpoint(req: ParquetDownloadRequest):
    if not HAS_PYARROW:
        return {"error": "pyarrow not installed — parquet loading unavailable"}
    try:
        path = await download_parquet(req.market_slug)
        return {"path": path, "slug": req.market_slug}
    except Exception as e:
        return {"error": str(e)}


@router.post("/run-parquet")
async def run_parquet_backtest(req: ParquetBacktestRequest):
    if not HAS_PYARROW:
        return {"error": "pyarrow not installed — parquet loading unavailable"}
    try:
        raw = load_parquet(req.file_path)
        price_series = parquet_to_price_series(raw)
        if not price_series:
            return {"error": "No price data in parquet file"}

        result = await run_backtest(
            slug=req.file_path,
            title=f"Parquet: {req.file_path}",
            clob_token_id="",
            strategy=req.strategy,
            bankroll=req.bankroll,
            kelly_fraction=req.kelly_fraction,
            price_series=price_series,
        )
        return {
            "slug": result.slug,
            "title": result.title,
            "strategy": result.strategy,
            "bankroll": result.bankroll,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "total_pnl": result.total_pnl,
            "pnl_pct": result.pnl_pct,
            "max_drawdown": result.max_drawdown,
            "sharpe": result.sharpe,
            "sortino": result.sortino,
            "profit_factor": result.profit_factor,
            "avg_edge": result.avg_edge,
            "equity_curve": result.equity_curve,
            "daily_pnl": result.daily_pnl,
            "trades": result.trades[:200],
        }
    except Exception as e:
        log.warning(f"Parquet backtest error: {e}")
        return {"error": str(e)}


@router.get("/results")
async def list_results(limit: int = 50):
    try:
        sb = get_supabase()
        res = sb.table("backtest_results").select("*").order("created_at", desc=True).limit(limit).execute()
        return {"results": res.data, "total": len(res.data)}
    except Exception as e:
        log.warning(f"Failed to fetch backtest results: {e}")
        return {"results": [], "total": 0}


@router.get("/results/{result_id}")
async def get_result(result_id: str):
    try:
        sb = get_supabase()
        res = sb.table("backtest_results").select("*").eq("id", result_id).single().execute()
        return res.data
    except Exception as e:
        log.warning(f"Failed to fetch backtest result {result_id}: {e}")
        return {"error": "Result not found"}
