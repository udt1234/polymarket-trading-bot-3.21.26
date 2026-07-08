"use client";

import { useCallback, useEffect, useState } from "react";
import Panel from "@/components/panel";
import ModuleCards from "@/components/module-cards";
import PositionsTable from "@/components/positions-table";
import OrdersTable from "@/components/orders-table";
import SignalsFeed from "@/components/signals-feed";
import BreakerBanner from "@/components/breaker-banner";
import PricePanel from "@/components/price-panel";
import { Module, SnapshotData, TerminalData } from "@/lib/types";

const POLL_MS = 15_000;

// Per-module health derived from Supabase (the bot API is firewalled, so we
// never HTTP it). TRADING = a trade in 24h; CYCLING = engine fresh + module
// not inactive; STUCK = module active/paper but engine stale; OFFLINE =
// inactive module.
function deriveHealth(
  data: TerminalData | null,
  m: Module,
  engineFresh: boolean
): string {
  if (m.status === "inactive") return "OFFLINE";
  if ((data?.trades_by_module?.[m.id] ?? 0) > 0) return "TRADING";
  return engineFresh ? "CYCLING" : "STUCK";
}

function engineIsFresh(lastCycleAt: string | null | undefined): boolean {
  if (!lastCycleAt) return false;
  return (Date.now() - new Date(lastCycleAt).getTime()) / 60_000 <= 12;
}

function engineBadge(lastCycleAt: string | null | undefined): {
  label: string;
  cls: string;
} {
  if (!lastCycleAt) return { label: "ENGINE: NO CYCLES", cls: "text-term-red" };
  const ageMin = (Date.now() - new Date(lastCycleAt).getTime()) / 60_000;
  if (ageMin <= 12)
    return {
      label: `ENGINE: CYCLING (${Math.max(0, Math.round(ageMin))}m ago)`,
      cls: "text-term-green",
    };
  return {
    label: `ENGINE: STALE (${Math.round(ageMin)}m ago)`,
    cls: "text-term-red",
  };
}

export default function Terminal() {
  const [data, setData] = useState<TerminalData | null>(null);
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

  const engineFresh = engineIsFresh(data?.last_cycle_at);
  const health = Object.fromEntries(
    (data?.modules ?? []).map((m) => [m.id, deriveHealth(data, m, engineFresh)])
  );

  return (
    <main className="mx-auto max-w-7xl space-y-4 p-4">
      <header className="flex items-baseline justify-between">
        <h1 className="text-base font-semibold uppercase tracking-widest text-term-text">
          Polymarket Maker Terminal
        </h1>
        <span className="text-xs text-term-muted">
          <span className={engineBadge(data?.last_cycle_at).cls}>
            {engineBadge(data?.last_cycle_at).label}
          </span>
          {" · read-only · polls 15s"}
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
