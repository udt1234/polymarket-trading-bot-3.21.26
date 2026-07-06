import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const db = supabaseServer();
    const requested = req.nextUrl.searchParams.get("bracket");

    // Distinct brackets from the most recent snapshots.
    const recent = await db
      .from("price_snapshots")
      .select("bracket")
      .order("snapshot_hour", { ascending: false })
      .limit(1000);
    if (recent.error) {
      return NextResponse.json({ error: recent.error.message }, { status: 500 });
    }
    const brackets = Array.from(
      new Set((recent.data ?? []).map((r) => r.bracket as string))
    );

    const bracket =
      requested && brackets.includes(requested) ? requested : brackets[0] ?? null;

    let points: { snapshot_hour: string; price: number }[] = [];
    if (bracket) {
      // Most recent 1000 points, returned in chronological order.
      const snaps = await db
        .from("price_snapshots")
        .select("snapshot_hour, price")
        .eq("bracket", bracket)
        .order("snapshot_hour", { ascending: false })
        .limit(1000);
      if (snaps.error) {
        return NextResponse.json({ error: snaps.error.message }, { status: 500 });
      }
      points = ((snaps.data ?? []) as typeof points).reverse();
    }

    return NextResponse.json({ brackets, bracket, points });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "unknown error" },
      { status: 500 }
    );
  }
}
