import { NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";
export const revalidate = 0;

export async function GET() {
  try {
    const db = supabaseServer();
    const [
      modules,
      openPositions,
      closedPositions,
      orders,
      signals,
      breaker,
      trades,
    ] = await Promise.all([
        db
          .from("modules")
          .select(
            "id, name, strategy, budget, status, inactive_reason, updated_at"
          )
          .order("name"),
        db
          .from("positions")
          .select("*")
          .in("status", ["open", "closing"])
          .order("opened_at", { ascending: false }),
        db
          .from("positions")
          .select("*")
          .eq("status", "closed")
          .order("closed_at", { ascending: false })
          .limit(15),
        db
          .from("orders")
          .select(
            "id, module_id, market_id, bracket, side, size, size_filled, price, status, executor, created_at"
          )
          .in("status", ["submitted", "open", "partially_filled"])
          .order("created_at", { ascending: false })
          .limit(100),
        db
          .from("signals")
          .select(
            "id, module_id, bracket, side, edge, model_prob, market_price, approved, rejection_reason, created_at"
          )
          .order("created_at", { ascending: false })
          .limit(50),
        db
          .from("settings")
          .select("value")
          .eq("key", "circuit_breaker")
          .maybeSingle(),
        db
          .from("trades")
          .select(
            "id, module_id, market_id, bracket, side, size, price, executor, executed_at"
          )
          .order("executed_at", { ascending: false })
          .limit(60),
      ]);

    // Engine liveness + per-module trade activity come from Supabase, not
    // HTTP: the bot API lives on a firewalled box (SSH-only), so the
    // dashboard and bot communicate ONLY through the database (BUILD_SPEC B5).
    const since24h = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const [lastCycle, recentTrades] = await Promise.all([
      db
        .from("logs")
        .select("message, created_at")
        .eq("log_type", "system")
        .ilike("message", "Cycle:%")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle(),
      db
        .from("trades")
        .select("module_id")
        .gte("executed_at", since24h),
    ]);

    const tradesByModule: Record<string, number> = {};
    for (const t of recentTrades.data ?? []) {
      const id = (t as { module_id: string | null }).module_id ?? "";
      if (id) tradesByModule[id] = (tradesByModule[id] ?? 0) + 1;
    }

    const firstError =
      modules.error ??
      openPositions.error ??
      closedPositions.error ??
      orders.error ??
      signals.error ??
      breaker.error ??
      trades.error;
    if (firstError) {
      return NextResponse.json({ error: firstError.message }, { status: 500 });
    }

    return NextResponse.json({
      modules: modules.data ?? [],
      positions: openPositions.data ?? [],
      closed_positions: closedPositions.data ?? [],
      orders: orders.data ?? [],
      signals: signals.data ?? [],
      trades: trades.data ?? [],
      circuit_breaker: breaker.data?.value ?? null,
      last_cycle_at: lastCycle.data?.created_at ?? null,
      last_cycle_message: lastCycle.data?.message ?? null,
      trades_by_module: tradesByModule,
      fetched_at: new Date().toISOString(),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "unknown error" },
      { status: 500 }
    );
  }
}
