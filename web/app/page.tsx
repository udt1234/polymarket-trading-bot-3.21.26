"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Panel from "@/components/panel";
import Tabs, { TabDef } from "@/components/tabs";
import ErrorBoundary from "@/components/error-boundary";
import PnlHero from "@/components/pnl-hero";
import StatCards from "@/components/stat-cards";
import ScanFeed from "@/components/scan-feed";
import StatusBar from "@/components/status-bar";
import PositionsTable from "@/components/positions-table";
import OrdersTable from "@/components/orders-table";
import BreakerBanner from "@/components/breaker-banner";
import PricePanel from "@/components/price-panel";
import FillsTape from "@/components/fills-tape";
import { Metrics, SnapshotData, TerminalData } from "@/lib/types";

const POLL_MS = 15_000;

const EMPTY_METRICS: Metrics = {
  realized_total: 0,
  unrealized_total: 0,
  closed_24h: 0,
  avg_edge: null,
  fill_rate: null,
  fills_24h: 0,
  open_orders: 0,
  breaker_trips: 0,
};

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
  return { label: `ENGINE: STALE (${Math.round(ageMin)}m ago)`, cls: "text-term-red" };
}

function moduleMetrics(d: TerminalData, mid: string): Metrics {
  const since24 = Date.now() - 24 * 3600 * 1000;
  const pts = d.pnl_series.filter((p) => p.module_id === mid);
  const sigs = d.signals.filter(
    (s) => s.module_id === mid && s.approved && s.edge != null
  );
  return {
    realized_total: pts.reduce((a, p) => a + p.d, 0),
    unrealized_total: d.positions
      .filter((p) => p.module_id === mid)
      .reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0),
    closed_24h: pts.filter((p) => new Date(p.t).getTime() >= since24).length,
    avg_edge: sigs.length
      ? sigs.reduce((a, s) => a + (s.edge ?? 0), 0) / sigs.length
      : null,
    fill_rate: null,
    fills_24h: d.trades_by_module[mid] ?? 0,
    open_orders: d.orders.filter((o) => o.module_id === mid).length,
    breaker_trips: 0,
  };
}

const LATENCY_ROWS = [
  ["CLOB round-trip (one order-post leg)", "~26ms p50", "31-40ms p95"],
  ["Order signing (kept off the hot path)", "~43ms p50", "spikes ~990ms cold"],
  ["Gamma data read", "~54ms p50", "232ms p95"],
  ["Hot-path fire (cancel + post pre-signed)", "~52ms", "≈ 2 × RTT"],
];

export default function Terminal() {
  const [data, setData] = useState<TerminalData | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotData | null>(null);
  const [bracket, setBracket] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("overview");

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

  const modules = data?.modules ?? [];
  const tabs: TabDef[] = useMemo(
    () => [
      { id: "overview", label: "Overview" },
      ...modules
        .filter((m) => m.status !== "inactive")
        .map((m) => ({ id: m.id, label: m.name })),
      { id: "latency", label: "Latency" },
    ],
    [modules]
  );

  const badge = engineBadge(data?.last_cycle_at);
  const metrics = data?.metrics ?? EMPTY_METRICS;
  const activeModule = modules.find((m) => m.id === tab) ?? null;

  return (
    <main className="mx-auto max-w-7xl space-y-4 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-base font-semibold uppercase tracking-widest text-term-text">
          Polymarket Maker <span className="text-term-gold">Terminal</span>
        </h1>
        <span className="text-xs text-term-muted">
          <span className={badge.cls}>{badge.label}</span>
          {" · read-only · polls 15s"}
          {data
            ? ` · updated ${new Date(data.fetched_at).toLocaleTimeString()}`
            : ""}
        </span>
      </header>

      {error && (
        <div className="rounded border border-term-red bg-term-red/15 px-3 py-2 text-term-red">
          data fetch failed: {error}
        </div>
      )}

      <BreakerBanner breaker={data?.circuit_breaker ?? null} />

      <Tabs tabs={tabs} active={tab} onChange={setTab} />

      {/* OVERVIEW */}
      {tab === "overview" && data && (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="space-y-4">
              <ErrorBoundary label="pnl chart">
                <PnlHero series={data.pnl_series} />
              </ErrorBoundary>
              <StatCards metrics={metrics} />
            </div>
            <div className="space-y-4">
              <Panel title={`Scan Engine · ${data.signals.length} signals`}>
                <ScanFeed signals={data.signals} modules={modules} />
              </Panel>
              <Panel title="Live Orders">
                <OrdersTable orders={data.orders} modules={modules} />
              </Panel>
            </div>
          </div>

          <StatusBar metrics={metrics} />

          <Panel title="Fills Tape: trades in / out">
            <FillsTape trades={data.trades} modules={modules} />
          </Panel>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Open Positions + Recent Closed">
              <PositionsTable
                positions={data.positions}
                closed={data.closed_positions}
                modules={modules}
              />
            </Panel>
            <Panel title="Price Snapshots">
              <ErrorBoundary label="price chart">
                <PricePanel data={snapshots} onSelectBracket={setBracket} />
              </ErrorBoundary>
            </Panel>
          </div>
        </div>
      )}

      {/* PER-MODULE */}
      {activeModule && data && (
        <div className="space-y-4">
          <ErrorBoundary label="pnl chart">
            <PnlHero
              series={data.pnl_series.filter(
                (p) => p.module_id === activeModule.id
              )}
              label={`${activeModule.name} · Realized`}
            />
          </ErrorBoundary>
          <StatCards metrics={moduleMetrics(data, activeModule.id)} />
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Signals">
              <ScanFeed
                signals={data.signals.filter(
                  (s) => s.module_id === activeModule.id
                )}
                modules={modules}
              />
            </Panel>
            <Panel title="Resting Orders">
              <OrdersTable
                orders={data.orders.filter(
                  (o) => o.module_id === activeModule.id
                )}
                modules={modules}
              />
            </Panel>
          </div>
          <Panel title="Positions">
            <PositionsTable
              positions={data.positions.filter(
                (p) => p.module_id === activeModule.id
              )}
              closed={data.closed_positions.filter(
                (p) => p.module_id === activeModule.id
              )}
              modules={modules}
            />
          </Panel>
        </div>
      )}

      {/* LATENCY */}
      {tab === "latency" && (
        <Panel title="Latency baseline · Dublin (AWS eu-west-1) → Polymarket">
          <table className="w-full text-sm">
            <tbody>
              {LATENCY_ROWS.map(([leg, p50, note]) => (
                <tr key={leg} className="border-b border-term-border/50">
                  <td className="px-3 py-2 text-term-text">{leg}</td>
                  <td className="px-3 py-2 text-right font-bold tabular-nums text-term-green">
                    {p50}
                  </td>
                  <td className="px-3 py-2 text-right text-term-muted">{note}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-3 py-2 text-xs text-term-muted">
            Measured 2026-07-11 (reads + signing, no orders). Signing jitter is
            why orders are pre-signed off the hot path. {badge.label}.
          </p>
        </Panel>
      )}

      {!data && !error && (
        <p className="px-3 py-8 text-center text-term-muted">loading…</p>
      )}
    </main>
  );
}
