"use client"

import { cn } from "@/lib/utils"

const ARCHETYPE_LABELS: Record<string, string> = {
  market_maker: "Market-Makers",
  tail_scooper: "Tail Scoopers",
  spike_trader: "Spike Traders",
  pace_chaser: "Pace Chasers",
  tail_punter: "Tail Punters",
}

const ARCHETYPE_ORDER = [
  "market_maker",
  "tail_scooper",
  "pace_chaser",
  "spike_trader",
  "tail_punter",
]

export interface ArchetypeRow {
  share: number
  dollars: number
  is_us: boolean
}

export function WhaleArchetypeBar({ breakdown }: { breakdown: Record<string, ArchetypeRow> }) {
  const rows = ARCHETYPE_ORDER.map((k) => ({ key: k, ...(breakdown[k] || { share: 0, dollars: 0, is_us: false }) }))
  const max = Math.max(0.0001, ...rows.map((r) => r.share))
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.key} className="flex items-center gap-2 text-xs">
          <span className={cn("w-32 font-medium", r.is_us && "text-primary")}>
            {ARCHETYPE_LABELS[r.key] || r.key}
          </span>
          <div className="h-2 flex-1 rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full",
                r.is_us ? "bg-primary" : "bg-muted-foreground/60",
              )}
              style={{ width: `${(r.share / max) * 100}%` }}
            />
          </div>
          <span className="w-12 text-right text-muted-foreground tabular-nums">
            {Math.round(r.share * 100)}%
          </span>
          <span className="w-24 text-right text-muted-foreground tabular-nums">
            ${Math.round(r.dollars).toLocaleString()}
          </span>
          {r.is_us && <span className="text-[10px] text-primary">← us</span>}
        </div>
      ))}
    </div>
  )
}
