import logging
import math
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"


@dataclass
class BacktestTrade:
    timestamp: str
    side: str
    size: float
    entry_price: float
    exit_price: float = 0
    pnl: float = 0
    edge: float = 0
    kelly_pct: float = 0
    model_prob: float = 0
    market_price: float = 0


@dataclass
class BacktestResult:
    id: str = ""
    slug: str = ""
    title: str = ""
    strategy: str = "mean_reversion"
    bankroll: float = 1000.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0
    total_pnl: float = 0
    pnl_pct: float = 0
    max_drawdown: float = 0
    sharpe: float = 0
    sortino: float = 0
    profit_factor: float = 0
    avg_edge: float = 0
    start_date: str = ""
    end_date: str = ""
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    daily_pnl: list = field(default_factory=list)


RELEVANCE_KEYWORDS = [
    "truth social", "posts", "tweets", "tweet", "count",
    "temperature", "how many", "number of",
]


async def fetch_gamma_events(query: str, limit: int = 20) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{GAMMA_BASE}/events", params={
            "q": query, "limit": min(limit * 3, 100),
        })
        res.raise_for_status()
        events = res.json()

        results = []
        for e in events:
            title = (e.get("title", "") or "").lower()
            slug = (e.get("slug", "") or "").lower()
            markets = e.get("markets", [])
            has_brackets = len(markets) >= 3

            query_lower = query.lower()
            title_match = query_lower in title or query_lower in slug
            keyword_match = any(kw in title for kw in RELEVANCE_KEYWORDS)

            if not (title_match or (keyword_match and has_brackets)):
                continue

            results.append({
                "id": e.get("id"),
                "title": e.get("title", ""),
                "slug": e.get("slug", ""),
                "end_date": e.get("endDate"),
                "volume": float(e.get("volume", 0) or 0),
                "markets": [
                    {
                        "group_item_title": m.get("groupItemTitle", m.get("question", "")),
                        "outcome_prices": m.get("outcomePrices", "[]"),
                        "clob_token_ids": m.get("clobTokenIds", "[]"),
                        "condition_id": m.get("conditionId", ""),
                        "slug": m.get("slug", ""),
                    }
                    for m in markets
                ],
            })
            if len(results) >= limit:
                break

        return results


async def fetch_price_history(clob_token_id: str, start_ts: int, end_ts: int, fidelity: int = 60) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(f"{GAMMA_BASE}/prices", params={
            "market": clob_token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "fidelity": fidelity,
        })
        if res.status_code != 200:
            return []
        data = res.json()
        if isinstance(data, dict) and "history" in data:
            return data["history"]
        if isinstance(data, list):
            return data
        return []


def _compute_model_prob(prices: list[float], strategy: str, idx: int) -> float | None:
    if idx < 5:
        return None

    window = prices[max(0, idx - 20):idx]
    if len(window) < 5:
        return None

    current = prices[idx]
    mean = sum(window) / len(window)
    std = math.sqrt(sum((p - mean) ** 2 for p in window) / len(window))
    std = max(std, 0.01)

    if strategy == "mean_reversion":
        z = (current - mean) / std
        model_prob = mean + (mean - current) * 0.3
        model_prob = max(0.01, min(0.99, model_prob))
    elif strategy == "momentum":
        if len(window) >= 5:
            recent = sum(window[-3:]) / 3
            older = sum(window[:3]) / 3
            momentum = recent - older
            model_prob = current + momentum * 0.5
        else:
            model_prob = current
        model_prob = max(0.01, min(0.99, model_prob))
    elif strategy == "ensemble":
        z = (current - mean) / std
        mr_prob = mean + (mean - current) * 0.3
        if len(window) >= 5:
            recent = sum(window[-3:]) / 3
            older = sum(window[:3]) / 3
            mom_prob = current + (recent - older) * 0.5
        else:
            mom_prob = current
        model_prob = 0.6 * mr_prob + 0.4 * mom_prob
        model_prob = max(0.01, min(0.99, model_prob))
    else:
        model_prob = mean
        model_prob = max(0.01, min(0.99, model_prob))

    return model_prob


def _kelly_size(model_prob: float, market_price: float, kelly_fraction: float) -> tuple[float, float, str]:
    edge = model_prob - market_price
    if market_price <= 0.01 or market_price >= 0.99:
        return edge, 0, "PASS"

    odds = (1 - market_price) / market_price
    full_kelly = model_prob - (1 - model_prob) / odds
    sized = full_kelly * kelly_fraction
    sized = max(0, min(sized, 0.15))

    if sized > 0.005 and edge > 0.02:
        return edge, sized, "BUY"
    return edge, 0, "PASS"


async def run_backtest(
    slug: str,
    title: str,
    clob_token_id: str,
    strategy: str = "mean_reversion",
    start_date: str = "",
    end_date: str = "",
    bankroll: float = 1000.0,
    kelly_fraction: float = 0.25,
    price_series: list[dict] | None = None,
) -> BacktestResult:
    now = datetime.utcnow()
    if end_date:
        end_dt = datetime.fromisoformat(end_date)
    else:
        end_dt = now
    if start_date:
        start_dt = datetime.fromisoformat(start_date)
    else:
        start_dt = end_dt - timedelta(days=30)

    if price_series:
        prices = []
        timestamps = []
        for p in price_series:
            t = p.get("t", p.get("timestamp", 0))
            price = float(p.get("p", p.get("price", 0)))
            if 0.01 <= price <= 0.99:
                prices.append(price)
                timestamps.append(int(t))
    else:
        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        fidelity = 60
        span_hours = (end_ts - start_ts) / 3600
        if span_hours > 720:
            fidelity = 360
        elif span_hours > 168:
            fidelity = 60

        raw_prices = await fetch_price_history(clob_token_id, start_ts, end_ts, fidelity)

        prices = []
        timestamps = []
        for p in raw_prices:
            t = p.get("t", p.get("timestamp", 0))
            price = float(p.get("p", p.get("price", 0)))
            if 0.01 <= price <= 0.99:
                prices.append(price)
                timestamps.append(int(t))

    if len(prices) < 10:
        return BacktestResult(
            slug=slug, title=title, strategy=strategy, bankroll=bankroll,
            start_date=start_date, end_date=end_date,
        )

    balance = bankroll
    peak = bankroll
    max_dd = 0.0
    trades = []
    equity_curve = [{"timestamp": timestamps[0], "value": bankroll}]
    daily_pnl_map = {}
    edges = []

    i = 0
    while i < len(prices) - 1:
        model_prob = _compute_model_prob(prices, strategy, i)
        if model_prob is None:
            i += 1
            continue

        market_price = prices[i]
        edge, kelly_pct, action = _kelly_size(model_prob, market_price, kelly_fraction)

        if action != "BUY":
            i += 1
            continue

        position_size = balance * kelly_pct
        exit_idx = min(i + max(5, len(prices) // 50), len(prices) - 1)
        exit_price = prices[exit_idx]

        if model_prob > market_price:
            pnl = position_size * (exit_price - market_price) / market_price
        else:
            pnl = position_size * (market_price - exit_price) / (1 - market_price)

        balance += pnl
        peak = max(peak, balance)
        dd = (peak - balance) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        ts_str = datetime.utcfromtimestamp(timestamps[i]).strftime("%Y-%m-%d %H:%M")
        trade = {
            "timestamp": ts_str,
            "side": "BUY" if model_prob > market_price else "SHORT",
            "size": round(position_size, 2),
            "entry_price": round(market_price, 4),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 2),
            "edge": round(edge, 4),
            "kelly_pct": round(kelly_pct, 4),
            "model_prob": round(model_prob, 4),
            "market_price": round(market_price, 4),
        }
        trades.append(trade)
        edges.append(edge)

        day_key = datetime.utcfromtimestamp(timestamps[i]).strftime("%Y-%m-%d")
        daily_pnl_map[day_key] = daily_pnl_map.get(day_key, 0) + pnl

        equity_curve.append({"timestamp": timestamps[exit_idx], "value": round(balance, 2)})
        i = exit_idx + 1

    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]

    daily_pnl = [{"date": k, "pnl": round(v, 2)} for k, v in sorted(daily_pnl_map.items())]

    sharpe = 0.0
    sortino = 0.0
    profit_factor = 0.0
    if trades:
        returns = [t["pnl"] / max(bankroll, 1) for t in trades]
        mean_ret = sum(returns) / len(returns)
        std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in returns) / max(len(returns) - 1, 1))
        downside = [r for r in returns if r < 0]
        downside_std = math.sqrt(sum(r ** 2 for r in downside) / max(len(downside) - 1, 1)) if downside else 0.001

        sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0
        sortino = (mean_ret / downside_std * math.sqrt(252)) if downside_std > 0 else 0

        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    total_pnl = balance - bankroll
    win_rate = (len(winning) / len(trades) * 100) if trades else 0

    return BacktestResult(
        slug=slug,
        title=title,
        strategy=strategy,
        bankroll=bankroll,
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=round(win_rate, 1),
        total_pnl=round(total_pnl, 2),
        pnl_pct=round(total_pnl / bankroll * 100, 2) if bankroll > 0 else 0,
        max_drawdown=round(max_dd, 4),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        profit_factor=round(profit_factor, 3) if profit_factor != float("inf") else 999.0,
        avg_edge=round(sum(edges) / len(edges), 4) if edges else 0,
        start_date=start_date or start_dt.strftime("%Y-%m-%d"),
        end_date=end_date or end_dt.strftime("%Y-%m-%d"),
        trades=trades,
        equity_curve=equity_curve,
        daily_pnl=daily_pnl,
    )
