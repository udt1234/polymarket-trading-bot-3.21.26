import { NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const db = supabaseServer();
    const [modules, openPositions, closedPositions, orders, signals, breaker] =
      await Promise.all([
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
      ]);

    const firstError =
      modules.error ??
      openPositions.error ??
      closedPositions.error ??
      orders.error ??
      signals.error ??
      breaker.error;
    if (firstError) {
      return NextResponse.json({ error: firstError.message }, { status: 500 });
    }

    return NextResponse.json({
      modules: modules.data ?? [],
      positions: openPositions.data ?? [],
      closed_positions: closedPositions.data ?? [],
      orders: orders.data ?? [],
      signals: signals.data ?? [],
      circuit_breaker: breaker.data?.value ?? null,
      fetched_at: new Date().toISOString(),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "unknown error" },
      { status: 500 }
    );
  }
}
