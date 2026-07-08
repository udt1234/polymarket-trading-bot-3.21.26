import { Module, Trade } from "@/lib/types";
import { fmtAgo, fmtCents, fmtSize, fmtUsd } from "@/lib/format";

// Trading-desk "tape": fills streaming in (BUY) and out (SELL), newest first.
// In paper mode this is sparse until there is volume; it fills up live as the
// engine trades. Polls with the rest of the terminal (15s).
export default function FillsTape({
  trades,
  modules,
}: {
  trades: Trade[];
  modules: Module[];
}) {
  if (trades.length === 0) {
    return (
      <p className="px-3 py-4 text-term-muted">
        no fills yet - the tape populates as the engine trades (sparse in paper
        mode until there is volume)
      </p>
    );
  }
  return (
    <div className="max-h-80 overflow-y-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-term-panel">
          <tr className="text-term-muted">
            <th className="px-3 py-1.5 font-normal">flow</th>
            <th className="px-3 py-1.5 font-normal">module</th>
            <th className="px-3 py-1.5 font-normal">bracket</th>
            <th className="px-3 py-1.5 text-right font-normal">size</th>
            <th className="px-3 py-1.5 text-right font-normal">price</th>
            <th className="px-3 py-1.5 text-right font-normal">notional</th>
            <th className="px-3 py-1.5 font-normal">mode</th>
            <th className="px-3 py-1.5 text-right font-normal">when</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const buy = t.side === "BUY";
            return (
              <tr key={t.id} className="border-t border-term-border/60">
                <td
                  className={`px-3 py-1.5 font-semibold ${
                    buy ? "text-term-green" : "text-term-red"
                  }`}
                >
                  {buy ? "▲ IN" : "▼ OUT"}
                </td>
                <td className="px-3 py-1.5">
                  {modules.find((m) => m.id === t.module_id)?.name ?? "?"}
                </td>
                <td className="px-3 py-1.5 text-term-accent">
                  {t.bracket ?? "-"}
                </td>
                <td className="px-3 py-1.5 text-right">{fmtSize(t.size)}</td>
                <td className="px-3 py-1.5 text-right">{fmtCents(t.price)}</td>
                <td className="px-3 py-1.5 text-right text-term-muted">
                  {fmtUsd(t.size * t.price)}
                </td>
                <td className="px-3 py-1.5 text-term-muted">{t.executor}</td>
                <td className="px-3 py-1.5 text-right text-term-muted">
                  {fmtAgo(t.executed_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
