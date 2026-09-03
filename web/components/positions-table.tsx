import { Module, Position } from "@/lib/types";
import { fmtCents, fmtSize, fmtTime, fmtUsd, pnlClass } from "@/lib/format";

function moduleName(modules: Module[], id: string): string {
  return modules.find((m) => m.id === id)?.name ?? "?";
}

export default function PositionsTable({
  positions,
  closed,
  modules,
}: {
  positions: Position[];
  closed: Position[];
  modules: Module[];
}) {
  const rows = [...positions, ...closed];
  if (rows.length === 0) {
    return <p className="px-3 py-4 text-term-muted">no positions</p>;
  }
  return (
    <table className="w-full text-left text-xs">
      <thead>
        <tr className="text-term-muted">
          <th className="px-3 py-1.5 font-normal">module</th>
          <th className="px-3 py-1.5 font-normal">bracket</th>
          <th className="px-3 py-1.5 font-normal">side</th>
          <th className="px-3 py-1.5 text-right font-normal">size</th>
          <th className="px-3 py-1.5 text-right font-normal">avg px</th>
          <th className="px-3 py-1.5 text-right font-normal">unrealized*</th>
          <th className="px-3 py-1.5 text-right font-normal">realized</th>
          <th className="px-3 py-1.5 font-normal">status</th>
          <th className="px-3 py-1.5 font-normal">opened</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((p) => (
          <tr key={p.id} className="border-t border-term-border/60">
            <td className="px-3 py-1.5">{moduleName(modules, p.module_id)}</td>
            <td className="px-3 py-1.5 text-term-accent">{p.bracket ?? "-"}</td>
            <td
              className={`px-3 py-1.5 ${
                p.side === "BUY" ? "text-term-green" : "text-term-red"
              }`}
            >
              {p.side}
            </td>
            <td className="px-3 py-1.5 text-right">{fmtSize(p.size)}</td>
            <td className="px-3 py-1.5 text-right">{fmtCents(p.avg_price)}</td>
            <td
              className={`px-3 py-1.5 text-right ${pnlClass(p.unrealized_pnl)}`}
            >
              {p.status === "closed" ? "-" : fmtUsd(p.unrealized_pnl)}
            </td>
            <td
              className={`px-3 py-1.5 text-right ${pnlClass(p.realized_pnl)}`}
            >
              {fmtUsd(p.realized_pnl)}
            </td>
            <td className="px-3 py-1.5">
              <span
                className={
                  p.status === "open"
                    ? "text-term-green"
                    : p.status === "closing"
                      ? "text-term-amber"
                      : "text-term-muted"
                }
              >
                {p.status}
              </span>
            </td>
            <td className="px-3 py-1.5 text-term-muted">
              {fmtTime(p.opened_at)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
