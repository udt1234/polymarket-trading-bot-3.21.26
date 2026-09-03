"use client";

import { Signal, Module } from "@/lib/types";
import { fmtCents } from "@/lib/format";

export default function ScanFeed({
  signals,
  modules,
}: {
  signals: Signal[];
  modules: Module[];
}) {
  const name = (id: string) =>
    modules.find((m) => m.id === id)?.name ?? id.slice(0, 6);
  if (!signals.length) {
    return <div className="p-3 text-term-muted">no signals yet</div>;
  }
  return (
    <div className="max-h-[420px] overflow-y-auto p-2 font-mono text-xs leading-relaxed">
      {signals.map((s) => {
        const ts = new Date(s.created_at).toLocaleTimeString("en-US", {
          hour12: false,
        });
        const edge = s.edge != null ? fmtCents(s.edge) : "-";
        return (
          <div
            key={s.id}
            className={s.approved ? "text-term-gold" : "text-term-muted"}
          >
            <span className="text-term-muted">[{ts}]</span>{" "}
            {s.approved ? "✓ EDGE" : "scan"}{" "}
            <span className="text-term-text">{name(s.module_id)}</span>
            {s.bracket ? ` · ${s.bracket}` : ""} · {s.side} · edge{" "}
            {edge}
            {s.approved
              ? " · sizing…"
              : s.rejection_reason
                ? ` · ${s.rejection_reason}`
                : " · no edge"}
          </div>
        );
      })}
    </div>
  );
}
