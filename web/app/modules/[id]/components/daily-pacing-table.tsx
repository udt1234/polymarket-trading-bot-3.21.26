import { formatDate, cn } from "@/lib/utils"

export function DailyPacingTable({ pacing }: { pacing: any }) {
  const ensembleBreakdown = pacing?.ensemble_breakdown as any[] | undefined
  const models = ensembleBreakdown?.map((m: any) => m.model) || []

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Daily Pacing
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">Day-by-day breakdown. Future dates show projected posts based on DOW averages.</p>
          </div>
        </div>
      </div>
      {pacing?.daily_table && pacing.daily_table.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-4 py-2 text-left">Date</th>
                <th className="px-4 py-2 text-left">Day</th>
                <th className="px-4 py-2 text-right">Daily Posts</th>
                <th className="px-4 py-2 text-right">Running Total</th>
                <th className="px-4 py-2 text-right">DOW Avg</th>
                <th className="px-4 py-2 text-right">DOW Weight</th>
                <th className="px-4 py-2 text-right">Deviation</th>
                <th className="px-4 py-2 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {pacing.daily_table.map((row: any, i: number) => (
                <tr
                  key={i}
                  className={cn(
                    "border-b border-border last:border-0",
                    row.is_today && "bg-primary/5 font-medium",
                    row.is_future && "text-muted-foreground italic"
                  )}
                >
                  <td className="px-4 py-2">{formatDate(row.date)}</td>
                  <td className="px-4 py-2">{row.day}</td>
                  <td className="px-4 py-2 text-right">
                    {row.is_future
                      ? <span className="text-muted-foreground italic" title="Projected from DOW avg">~{(row.dow_avg ?? 0).toFixed(0)}</span>
                      : (row.daily_posts ?? "—")}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {row.is_future
                      ? <span className="text-muted-foreground italic">—</span>
                      : (row.running_total ?? "—")}
                  </td>
                  <td className="px-4 py-2 text-right">{(row.dow_avg ?? 0).toFixed(1)}</td>
                  <td className="px-4 py-2 text-right">{(row.dow_weight ?? 0).toFixed(3)}</td>
                  <td className={cn(
                    "px-4 py-2 text-right font-mono",
                    row.status === "ahead" && "text-success",
                    row.status === "behind" && "text-destructive",
                    row.status === "on_pace" && "text-muted-foreground",
                  )}>
                    {row.deviation != null ? `${row.deviation > 0 ? "+" : ""}${row.deviation.toFixed(1)}` : "—"}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {row.status === "ahead" && <span className="text-success">&#9650;</span>}
                    {row.status === "behind" && <span className="text-destructive">&#9660;</span>}
                    {row.status === "on_pace" && <span className="text-muted-foreground">&#9679;</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-6 py-8 text-center text-sm text-muted-foreground">No pacing data yet</p>
      )}
    </div>
  )
}
