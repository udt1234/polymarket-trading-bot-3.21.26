"use client"

import { cn } from "@/lib/utils"

export interface GridRow {
  archetype: string
  median_entry_hour: number | null
  median_entry_price: number | null
  avg_fill_size_usd: number | null
  fills_count: number
}

const LABELS: Record<string, string> = {
  market_maker: "Market-Maker",
  tail_scooper: "Tail Scooper",
  spike_trader: "Spike Trader",
  pace_chaser: "Pace Chaser",
  tail_punter: "Tail Punter",
}

export function WhaleGrid({ rows }: { rows: GridRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 text-left">Archetype</th>
            <th className="px-2 py-1.5 text-right">Fills</th>
            <th className="px-2 py-1.5 text-right">Median entry hr</th>
            <th className="px-2 py-1.5 text-right">Median entry px</th>
            <th className="px-2 py-1.5 text-right">Avg size</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.archetype} className="border-t border-border/40">
              <td className="px-2 py-1.5 font-medium">{LABELS[r.archetype] || r.archetype}</td>
              <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">
                {r.fills_count}
              </td>
              <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">
                {r.median_entry_hour !== null ? `h${r.median_entry_hour.toFixed(1)}` : "—"}
              </td>
              <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">
                {r.median_entry_price !== null ? `$${r.median_entry_price.toFixed(2)}` : "—"}
              </td>
              <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">
                {r.avg_fill_size_usd !== null ? `$${r.avg_fill_size_usd.toFixed(0)}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
