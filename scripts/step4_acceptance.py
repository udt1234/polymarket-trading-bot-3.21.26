"""BUILD_SPEC PART J Step 4 acceptance test.

Runs ONE real engine cycle in paper mode against live data: S2 + Copytrader
evaluate, signals pass the risk gate, paper orders rest. Then simulates a
dip crossing our best resting BUY so the paper executor fills it, and a
partial SELL fill, verifying positions + realized P&L rows are written
correctly. Cleans up its own paper rows at the end.

Run: python -u scripts/step4_acceptance.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.polymarket_proxy import install_httpx_proxy_patch

install_httpx_proxy_patch()

from api.dependencies import get_supabase  # noqa: E402
from api.modules import ModuleRegistry  # noqa: E402
from api.services.engine import Engine  # noqa: E402
from api.services.executor import PaperExecutor  # noqa: E402


def main() -> None:
    sb = get_supabase()
    registry = ModuleRegistry()
    registry.discover()
    print(f"modules registered: {[m.name for m in registry.all_modules()]}")

    print("\n== 1. one engine cycle (paper, live data) ==")
    engine = Engine(registry)
    summary = engine.cycle()
    print(f"  summary: {summary}")

    orders = (sb.table("orders").select("*").eq("executor", "paper")
              .eq("status", "open").order("created_at", desc=True).execute().data) or []
    print(f"  resting paper orders: {len(orders)}")
    for o in orders[:8]:
        print(f"   - [{o['side']}] {o['bracket']} {float(o['price']):.3f} x {float(o['size']):.0f}")
    if not orders:
        print("ACCEPT FAIL: no paper orders rested (check risk-gate rejections above)")
        return

    print("\n== 2. simulate a dip -> paper BUY fill ==")
    target = orders[0]
    fake_quotes = {target["token_id"]: {"best_bid": float(target["price"]),
                                        "best_ask": float(target["price"])}}
    fills = PaperExecutor().check_fills(fake_quotes)
    print(f"  fills: {fills}")

    pos = (sb.table("positions").select("*").eq("market_id", target["market_id"])
           .eq("bracket", target["bracket"]).eq("status", "open")
           .limit(1).execute().data)
    if not pos:
        print("ACCEPT FAIL: fill did not create a position")
        return
    p = pos[0]
    print(f"  position: {p['bracket']} size={float(p['size']):.0f} avg={float(p['avg_price']):.3f}")

    print("\n== 3. SELL half -> realized P&L accumulates ==")
    from api.services.position_manager import apply_sell_fill, claim_for_exit
    sell_price = round(float(p["avg_price"]) + 0.05, 3)
    half = float(p["size"]) / 2
    assert claim_for_exit(p["id"]), "atomic claim failed"
    after = apply_sell_fill(p["id"], sell_price, half)
    expected = (sell_price - float(p["avg_price"])) * half
    print(f"  sold {half:.0f} @ {sell_price:.3f} -> realized_pnl={float(after['realized_pnl']):.4f} "
          f"(expected {expected:.4f}) status={after['status']} size={float(after['size']):.0f}")
    pnl_ok = abs(float(after["realized_pnl"]) - expected) < 1e-6 and after["status"] == "open"

    print("\n== 4. close remainder -> closed_at set ==")
    assert claim_for_exit(p["id"]), "second claim failed"
    closed = apply_sell_fill(p["id"], sell_price, float(after["size"]))
    closed_ok = closed["status"] == "closed" and closed.get("closed_at") and float(closed["size"]) == 0
    print(f"  status={closed['status']} closed_at={closed.get('closed_at')} "
          f"total realized={float(closed['realized_pnl']):.4f}")

    print("\n== 5. cleanup test paper rows ==")
    sb.table("positions").delete().eq("id", p["id"]).execute()
    for o in orders:
        sb.table("orders").delete().eq("id", o["id"]).execute()
    sb.table("trades").delete().eq("market_id", target["market_id"]).execute()
    print("  cleaned")

    ok = summary["approved"] > 0 and fills > 0 and pnl_ok and closed_ok
    print("\nACCEPT PASS" if ok else "\nACCEPT FAIL")


if __name__ == "__main__":
    main()
