import { Metrics } from "@/lib/types";
import { fmtUsd, fmtCents, fmtPct } from "@/lib/format";

function Card({
  label,
  value,
  cls,
}: {
  label: string;
  value: string;
  cls?: string;
}) {
  return (
    <div className="rounded border border-term-border bg-term-panel p-3">
      <div className="text-[10px] uppercase tracking-widest text-term-muted">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${cls ?? "text-term-text"}`}>
        {value}
      </div>
    </div>
  );
}

export default function StatCards({
  metrics,
  latencyMs = 26,
}: {
  metrics: Metrics;
  latencyMs?: number;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <Card label="Closed 24h" value={String(metrics.closed_24h)} />
      <Card
        label="Avg Edge"
        value={metrics.avg_edge != null ? fmtCents(metrics.avg_edge) : "-"}
        cls="text-term-gold"
      />
      <Card
        label="Fill Rate"
        value={metrics.fill_rate != null ? fmtPct(metrics.fill_rate) : "-"}
      />
      <Card
        label="Breaker Trips"
        value={String(metrics.breaker_trips)}
        cls={metrics.breaker_trips > 0 ? "text-term-red" : "text-term-text"}
      />
      <Card label="CLOB RTT" value={`~${latencyMs}ms`} cls="text-term-green" />
      <Card
        label="Unrealized"
        value={fmtUsd(metrics.unrealized_total)}
        cls={metrics.unrealized_total >= 0 ? "text-term-green" : "text-term-red"}
      />
    </div>
  );
}
