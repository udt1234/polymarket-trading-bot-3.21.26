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

// Per-tab description + when it's expected to fire, so paper activity reads
// correctly (a quiet module isn't broken - it just hasn't met its trigger).
const MODULE_INFO: Record<string, { what: string; fires: string }> = {
  overview: {
    what: "Aggregate of every module — combined realized P/L, the live resting orders, and fills across all strategies.",
    fires: "Always on; each module runs every ~5-min engine cycle.",
  },
  arb_scanner: {
    what: "Complete-set arbitrage — buy every outcome of one event for a combined price < $1 (riskless, since exactly one pays $1).",
    fires: "Only when a mispriced set actually appears — RARE on an efficient market, so 0 orders is normal/correct, not broken.",
  },
  copytrader: {
    what: "Whale-informed tweet quoter — a proven whale picks which live ELON tweet brackets to quote; we rest our OWN fair-value bid there.",
    fires: "Only when that whale is trading live Elon tweet brackets; idle by design otherwise (Elon markets are efficient, so it's thin).",
  },
  lp_rewards: {
    what: "Liquidity-reward farming — rests post-only bids near mid on reward-eligible markets to earn Polymarket LP rewards (income that doesn't need a directional edge).",
    fires: "Every cycle on markets with a reward pool. Orders REST to earn rewards and rarely fill — so 'no positions' is EXPECTED; a position only appears if a bid gets crossed.",
  },
  mirror_trader: {
    what: "Copytrader (Option A) — follows proven whales' BUYS as a resting maker, sized down, across ANY market (0xd218 +103%, pada +92%).",
    fires: "Every cycle when a currently-winning whale has recent buys. We rest at/BELOW the whale's price, so it fills only when the market comes to us (often it won't = no position).",
  },
  s2_basket_hold: {
    what: "Buys Elon tweet-count brackets at our pace-model fair value and HOLDS to resolution. The most active strategy.",
    fires: "On every live Elon tweet auction — fills + positions accrue here (162 fills, 6 open / 7 closed so far).",
  },
  sports_sweep: {
    what: "Rests deep-discount bids on a DECIDED sports favorite (garbage-time) and holds to resolution. Backtest = paper-only (edge dies with realism).",
    fires: "Only when a live game has a near-certain favorite (bid ≥ 97%) — mostly late innings of blowouts, so it's quiet most of the day.",
  },
  latency: {
    what: "Measured Dublin → Polymarket round-trip latency baseline (reads + signing).",
    fires: "Static reference; re-measured on demand.",
  },
};

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
  const liveModules = modules.filter((m) => m.status === "active");
  const mode =
    liveModules.length > 0
      ? {
          label: `⚠ LIVE MONEY — ${liveModules.length} module(s) trading real funds`,
          cls: "border-term-red bg-term-red/15 text-term-red",
        }
      : {
          label: "PAPER MODE · all modules simulated · no real money at risk",
          cls: "border-term-amber bg-term-amber/15 text-term-amber",
        };
  const statusChip = (s: string) =>
    s === "active"
      ? "border-term-red/50 bg-term-red/15 text-term-red"
      : s === "paper"
        ? "border-term-amber/50 bg-term-amber/15 text-term-amber"
        : "border-term-muted/40 bg-term-muted/15 text-term-muted";

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

      {data && modules.length > 0 && (
        <div
          className={`rounded border px-3 py-1.5 text-center text-xs font-semibold uppercase tracking-widest ${mode.cls}`}
        >
          {mode.label}
        </div>
      )}

      <Tabs tabs={tabs} active={tab} onChange={setTab} />

      {(() => {
        const key =
          tab === "overview" || tab === "latency"
            ? tab
            : activeModule?.strategy ?? "";
        const info = MODULE_INFO[key];
        return info ? (
          <div className="rounded border border-term-border bg-term-panel/60 px-3 py-2 text-xs leading-relaxed">
            <span className="text-term-text">{info.what}</span>{" "}
            <span className="text-term-gold">· Fires: {info.fires}</span>
          </div>
        ) : null;
      })()}

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
              <Panel title="Live Orders · resting quotes (filled=0 means NOT a position yet)">
                <OrdersTable orders={data.orders} modules={modules} />
              </Panel>
              <div className="rounded border border-term-border bg-term-panel/60 px-3 py-2 text-xs text-term-muted">
                Per-module decisions (signals: approved ✓ or why-rejected) now live in
                each module&apos;s own tab. Pick a module above to see its decisions.
              </div>
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
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold uppercase tracking-wider text-term-text">
              {activeModule.name}
            </span>
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${statusChip(activeModule.status)}`}
            >
              {activeModule.status === "paper"
                ? "PAPER"
                : activeModule.status === "active"
                  ? "LIVE $"
                  : activeModule.status}
            </span>
          </div>
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
