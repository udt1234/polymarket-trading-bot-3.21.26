import { Module, Signal } from "@/lib/types";
import { fmtCents, fmtPct, fmtTime } from "@/lib/format";

export default function SignalsFeed({
  signals,
  modules,
}: {
  signals: Signal[];
  modules: Module[];
}) {
  if (signals.length === 0) {
    return <p className="px-3 py-4 text-term-muted">no signals yet</p>;
  }
  return (
    <div className="max-h-80 overflow-y-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-term-panel">
          <tr className="text-term-muted">
            <th className="px-3 py-1.5 font-normal">time</th>
            <th className="px-3 py-1.5 font-normal">module</th>
            <th className="px-3 py-1.5 font-normal">side</th>
            <th className="px-3 py-1.5 font-normal">bracket</th>
            <th className="px-3 py-1.5 text-right font-normal">edge</th>
            <th className="px-3 py-1.5 text-right font-normal">model</th>
            <th className="px-3 py-1.5 text-right font-normal">market</th>
            <th className="px-3 py-1.5 font-normal">verdict</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.id} className="border-t border-term-border/60">
              <td className="px-3 py-1.5 text-term-muted">
                {fmtTime(s.created_at)}
              </td>
              <td className="px-3 py-1.5">
                {modules.find((m) => m.id === s.module_id)?.name ?? "?"}
              </td>
              <td
                className={`px-3 py-1.5 ${
                  s.side === "BUY" ? "text-term-green" : "text-term-red"
                }`}
              >
                {s.side}
              </td>
              <td className="px-3 py-1.5 text-term-accent">
                {s.bracket ?? "-"}
              </td>
              <td className="px-3 py-1.5 text-right">{fmtPct(s.edge)}</td>
              <td className="px-3 py-1.5 text-right">{fmtPct(s.model_prob)}</td>
              <td className="px-3 py-1.5 text-right">
                {fmtCents(s.market_price)}
              </td>
              <td className="px-3 py-1.5">
                {s.approved ? (
                  <span className="text-term-green">approved</span>
                ) : (
                  <span
                    className="text-term-red"
                    title={s.rejection_reason ?? undefined}
                  >
                    {s.rejection_reason ?? "rejected"}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
