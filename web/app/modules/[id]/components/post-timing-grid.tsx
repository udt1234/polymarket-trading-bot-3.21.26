"use client"

import { cn } from "@/lib/utils"

const DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

export function PostTimingGrid({ data }: { data: Array<{ dow: number; hour: number; count: number }> }) {
  const grid: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0))
  let max = 0
  for (const d of data || []) {
    if (d.dow >= 0 && d.dow < 7 && d.hour >= 0 && d.hour < 24) {
      grid[d.dow][d.hour] = d.count
      if (d.count > max) max = d.count
    }
  }

  const color = (v: number) => {
    if (v <= 0 || max <= 0) return "hsl(217, 33%, 17%)"
    const intensity = Math.min(1, v / max)
    const hue = 142 - intensity * 120
    return `hsl(${hue}, 70%, ${30 + intensity * 30}%)`
  }

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Post Timing Heatmap</h2>
      <p className="mb-4 text-xs text-muted-foreground">Posts by day × hour (green = more posts)</p>
      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          <div className="flex">
            <div className="w-10 flex-shrink-0" />
            <div className="flex-1 grid grid-cols-24 gap-[2px]" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
              {Array.from({ length: 24 }).map((_, h) => (
                <div key={h} className="text-center text-[9px] text-muted-foreground">{h}</div>
              ))}
            </div>
          </div>
          {DOWS.map((d, dow) => (
            <div key={dow} className="flex items-center mt-[2px]">
              <div className="w-10 flex-shrink-0 text-[10px] text-muted-foreground">{d}</div>
              <div className="flex-1 grid gap-[2px]" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
                {grid[dow].map((v, h) => (
                  <div
                    key={h}
                    className="aspect-square rounded-[2px]"
                    style={{ backgroundColor: color(v) }}
                    title={`${d} ${h}:00 — ${v.toFixed(1)} posts`}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
