"use client";

import { useCallback, useEffect, useState } from "react";
import Panel from "@/components/panel";
import ModuleCards from "@/components/module-cards";
import PositionsTable from "@/components/positions-table";
import OrdersTable from "@/components/orders-table";
import SignalsFeed from "@/components/signals-feed";
import BreakerBanner from "@/components/breaker-banner";
import PricePanel from "@/components/price-panel";
import { SnapshotData, TerminalData } from "@/lib/types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 15_000;

async function fetchHealth(moduleId: string): Promise<string> {
  try {
    const res = await fetch(
      `${API_URL}/api/engine/health?module_id=${encodeURIComponent(moduleId)}`,
      { cache: "no-store" }
    );
    if (!res.ok) return "OFFLINE";
    const body = await res.json();
    const state = body.state ?? body.status ?? body.health;
    return typeof state === "string" ? state.toUpperCase() : "OFFLINE";
  } catch {
    return "OFFLINE";
  }
}

export default function Terminal() {
  const [data, setData] = useState<TerminalData | null>(null);
  const [health, setHealth] = useState<Record<string, string>>({});
  const [snapshots, setSnapshots] = useState<SnapshotData | null>(null);
  const [bracket, setBracket] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/terminal", { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? `HTTP ${res.status}`);
      setData(body);
      setError(null);

      const entries = await Promise.all(
        (body.modules ?? []).map(async (m: { id: string }) => [
          m.id,
          await fetchHealth(m.id),
        ])
      );
      setHealth(Object.fromEntries(entries));
    } catch (e) {
      setError(e instanceof Error ? e.message : "fetch failed");
    }
    try {
      const qs = bracket ? `?bracket=${encodeURIComponent(bracket)}` : "";
      const res = await fetch(`/api/snapshots${qs}`, { cache: "no-store" });
      if (res.ok) setSnapshots(await res.json());
    } catch {
      // price panel keeps its last state
    }
  }, [bracket]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <main className="mx-auto max-w-7xl space-y-4 p-4">
      <header className="flex items-baseline justify-between">
        <h1 className="text-base font-semibold uppercase tracking-widest text-term-text">
          Polymarket Maker Terminal
        </h1>
        <span className="text-xs text-term-muted">
          read-only · polls 15s
          {data ? ` · updated ${new Date(data.fetched_at).toLocaleTimeString()}` : ""}
        </span>
      </header>

      {error && (
        <div className="rounded border border-term-red bg-term-red/15 px-3 py-2 text-term-red">
          data fetch failed: {error}
        </div>
      )}

      <BreakerBanner breaker={data?.circuit_breaker ?? null} />

      <ModuleCards modules={data?.modules ?? []} health={health} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Open Positions + Recent Closed">
          <PositionsTable
            positions={data?.positions ?? []}
            closed={data?.closed_positions ?? []}
            modules={data?.modules ?? []}
          />
        </Panel>
        <Panel title="Resting Orders">
          <OrdersTable
            orders={data?.orders ?? []}
            modules={data?.modules ?? []}
          />
        </Panel>
      </div>

      <Panel title="Price Snapshots">
        <PricePanel data={snapshots} onSelectBracket={setBracket} />
      </Panel>

      <Panel title="Signals (last 50)">
        <SignalsFeed
          signals={data?.signals ?? []}
          modules={data?.modules ?? []}
        />
      </Panel>
    </main>
  );
}
