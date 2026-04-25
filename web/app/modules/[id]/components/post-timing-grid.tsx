"use client"

const DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

const HOUR_LABELS = Array.from({ length: 24 }, (_, h) => {
  if (h === 0) return "12 AM"
  if (h === 12) return "12 PM"
  return h < 12 ? `${h} AM` : `${h - 12} PM`
})

const COLORS = {
  none: "#e5e7eb",
  low: "#4b5563",
  mid: "#eab308",
  high: "#ef4444",
}

const TEXT = {
  none: "#9ca3af",
  low: "#f3f4f6",
  mid: "#1f2937",
  high: "#ffffff",
}

function tier(v: number, max: number): "none" | "low" | "mid" | "high" {
  if (v <= 0 || max <= 0) return "none"
  const ratio = v / max
  if (ratio > 0.7) return "high"
  if (ratio > 0.4) return "mid"
  return "low"
}

export function PostTimingGrid({ data }: { data: Array<{ dow: number; hour: number; count: number }> }) {
  const grid: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0))
  let max = 0
  for (const d of data || []) {
    if (d.dow >= 0 && d.dow < 7 && d.hour >= 0 && d.hour < 24) {
      grid[d.dow][d.hour] = d.count
      if (d.count > max) max = d.count
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Post Timing Heatmap</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        Avg posts per hour across years of historical data.
        <span className="ml-2 inline-flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS.high }} /> High
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS.mid }} /> Mid
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS.low }} /> Low
          <span className="inline-block h-2.5 w-2.5 rounded-sm border border-border" style={{ backgroundColor: COLORS.none }} /> None
        </span>
      </p>
      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          <div className="flex">
            <div className="w-10 flex-shrink-0" />
            <div className="flex-1 grid gap-[2px]" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
              {HOUR_LABELS.map((label, h) => (
                <div key={h} className="text-center text-[9px] leading-tight text-muted-foreground whitespace-nowrap">{label}</div>
              ))}
            </div>
          </div>
          {DOWS.map((d, dow) => (
            <div key={dow} className="flex items-center mt-[2px]">
              <div className="w-10 flex-shrink-0 text-[10px] text-muted-foreground">{d}</div>
              <div className="flex-1 grid gap-[2px]" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
                {grid[dow].map((v, h) => {
                  const t = tier(v, max)
                  const display = v > 0 ? (v >= 10 ? Math.round(v).toString() : v.toFixed(1)) : ""
                  return (
                    <div
                      key={h}
                      className="aspect-square rounded-[2px] flex items-center justify-center"
                      style={{ backgroundColor: COLORS[t], color: TEXT[t] }}
                      title={`${d} ${HOUR_LABELS[h]} — ${v.toFixed(2)} avg posts`}
                    >
                      <span className="text-[8px] font-semibold leading-none">{display}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
