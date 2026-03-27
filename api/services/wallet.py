import httpx
import logging

log = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"


async def fetch_wallet_positions(wallet_address: str, limit: int = 100) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.get(
                f"{DATA_API}/positions",
                params={"user": wallet_address.lower(), "limit": limit},
            )
            res.raise_for_status()
            return res.json()
        except Exception as e:
            log.error(f"Failed to fetch wallet positions: {e}")
            return []


async def fetch_wallet_trades(wallet_address: str, limit: int = 50) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            res = await client.get(
                f"{DATA_API}/trades",
                params={"user": wallet_address.lower(), "limit": limit},
            )
            res.raise_for_status()
            return res.json()
        except Exception as e:
            log.error(f"Failed to fetch wallet trades: {e}")
            return []


def _is_resolved(p: dict) -> bool:
    from datetime import datetime, timezone
    redeemable = p.get("redeemable", False)
    cur_price = float(p.get("curPrice", 0) or 0)
    end_date = p.get("endDate", "")
    if redeemable:
        return True
    if cur_price == 0 or cur_price == 1.0:
        if end_date:
            try:
                end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                return datetime.now(timezone.utc) > end
            except Exception:
                pass
        return cur_price == 0
    return False


async def fetch_wallet_summary(wallet_address: str) -> dict:
    positions = await fetch_wallet_positions(wallet_address)

    portfolio_value = 0.0
    total_invested = 0.0
    total_pnl = 0.0
    open_count = 0
    closed_count = 0
    wins = 0

    for p in positions:
        size = float(p.get("size", 0) or 0)
        cur_price = float(p.get("curPrice", 0) or 0)
        initial_value = float(p.get("initialValue", 0) or 0)
        cash_pnl = float(p.get("cashPnl", 0) or 0)
        market_value = size * cur_price

        total_invested += initial_value
        total_pnl += cash_pnl

        if _is_resolved(p):
            closed_count += 1
            if cash_pnl > 0:
                wins += 1
        else:
            portfolio_value += market_value
            open_count += 1

    return {
        "wallet_address": wallet_address,
        "portfolio_value": portfolio_value,
        "total_invested": total_invested,
        "total_pnl": total_pnl,
        "open_count": open_count,
        "closed_count": closed_count,
        "wins": wins,
        "losses": closed_count - wins,
        "win_rate": (wins / closed_count * 100) if closed_count else 0,
        "total_positions": len(positions),
    }


async def fetch_wallet_auctions(wallet_address: str) -> list[dict]:
    positions = await fetch_wallet_positions(wallet_address)

    events: dict[str, list[dict]] = {}
    for p in positions:
        slug = p.get("eventSlug", p.get("slug", "unknown"))
        events.setdefault(slug, [])
        events[slug].append(p)

    auctions = []
    for slug, group in events.items():
        group_value = 0.0
        group_cost = 0.0
        group_pnl = 0.0
        bids = []

        for p in group:
            size = float(p.get("size", 0) or 0)
            cur_price = float(p.get("curPrice", 0) or 0)
            avg_price = float(p.get("avgPrice", 0) or 0)
            initial_value = float(p.get("initialValue", 0) or 0)
            cash_pnl = float(p.get("cashPnl", 0) or 0)
            market_value = size * cur_price

            group_value += market_value
            group_cost += initial_value
            group_pnl += cash_pnl

            bids.append({
                "title": p.get("title", ""),
                "outcome": p.get("outcome", ""),
                "size": size,
                "avg_price": avg_price,
                "cur_price": cur_price,
                "market_value": market_value,
                "cost": initial_value,
                "pnl": cash_pnl,
                "pnl_pct": float(p.get("percentPnl", 0) or 0),
            })

        all_resolved = all(_is_resolved(p) for p in group)
        if all_resolved:
            status = "won" if group_pnl > 0 else "lost"
        else:
            status = "open"

        end_date = ""
        for p in group:
            ed = p.get("endDate", "")
            if ed:
                end_date = ed[:10]
                break

        title = group[0].get("title", slug)
        # Clean up title — remove outcome suffix like "Yes", "No"
        for p in group:
            t = p.get("title", "")
            if t and len(t) > len(title):
                title = t

        auctions.append({
            "slug": slug,
            "title": title,
            "status": status,
            "end_date": end_date,
            "total_cost": group_cost,
            "total_value": group_value,
            "total_pnl": group_pnl,
            "bid_count": len(group),
            "bids": sorted(bids, key=lambda b: abs(b["pnl"]), reverse=True),
        })

    return sorted(auctions, key=lambda a: (
        0 if a["status"] == "open" else 1,
        a.get("end_date", "") or "9999",
    ))
