import { Module } from "@/lib/types";
import { fmtUsd } from "@/lib/format";

const STATUS_STYLE: Record<string, string> = {
  active: "bg-term-green/15 text-term-green border-term-green/40",
  paper: "bg-term-amber/15 text-term-amber border-term-amber/40",
  inactive: "bg-term-muted/15 text-term-muted border-term-muted/40",
};

const HEALTH_STYLE: Record<string, string> = {
  TRADING: "text-term-green",
  CYCLING: "text-term-accent",
  STUCK: "text-term-red",
  OFFLINE: "text-term-muted",
};

export default function ModuleCards({
  modules,
  health,
}: {
  modules: Module[];
  health: Record<string, string>;
}) {
  if (modules.length === 0) {
    return (
      <p className="px-3 py-4 text-term-muted">no modules registered</p>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {modules.map((m) => {
        const h = health[m.id] ?? "OFFLINE";
        return (
          <div
            key={m.id}
            className="rounded border border-term-border bg-term-panel p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="font-semibold text-term-text">{m.name}</span>
              <span
                className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                  STATUS_STYLE[m.status] ?? STATUS_STYLE.inactive
                }`}
              >
                {m.status === "active" ? "REAL $" : m.status}
              </span>
            </div>
            <div className="mt-2 space-y-1 text-xs">
              <div className="flex justify-between">
                <span className="text-term-muted">health</span>
                <span className={HEALTH_STYLE[h] ?? "text-term-muted"}>
                  {h}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-term-muted">strategy</span>
                <span>{m.strategy}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-term-muted">budget</span>
                <span>{fmtUsd(m.budget)}</span>
              </div>
              {m.status === "inactive" && m.inactive_reason && (
                <div className="truncate text-term-red" title={m.inactive_reason}>
                  {m.inactive_reason}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
