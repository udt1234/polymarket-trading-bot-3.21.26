import { Metrics } from "@/lib/types";
import { fmtUsd } from "@/lib/format";

export default function StatusBar({ metrics }: { metrics: Metrics }) {
  const item = (label: string, value: string, cls?: string) => (
    <span className="text-term-muted">
      {label}: <span className={cls ?? "text-term-text"}>{value}</span>
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded border border-term-border bg-term-panel px-3 py-2 text-xs">
      {item("Open orders", String(metrics.open_orders))}
      {item(
        "Inv uPnL",
        fmtUsd(metrics.unrealized_total),
        metrics.unrealized_total >= 0 ? "text-term-green" : "text-term-red"
      )}
      {item("Fills 24h", String(metrics.fills_24h))}
      {item("Closed 24h", String(metrics.closed_24h))}
      {item(
        "Realized",
        fmtUsd(metrics.realized_total),
        metrics.realized_total >= 0 ? "text-term-green" : "text-term-red"
      )}
    </div>
  );
}
