"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"

function fmt(n: number, decimals = 1): string {
  return parseFloat(n.toFixed(decimals)).toString()
}

function heatColor(value: number, min: number, max: number): string {
  const range = max - min || 1
  const intensity = (value - min) / range
  // High=red, Mid=orange, Low=grey
  if (intensity > 0.66) {
    const t = (intensity - 0.66) / 0.34
    return `hsl(${10 - t * 10}, ${70 + t * 15}%, ${35 + t * 10}%)`
  }
  if (intensity > 0.33) {
    const t = (intensity - 0.33) / 0.33
    return `hsl(${30 - t * 20}, ${50 + t * 20}%, ${30 + t * 5}%)`
  }
  return `hsl(220, ${8 + intensity * 15}%, ${25 + intensity * 10}%)`
}

interface DowHourRow {
  dow: number
  day: string
  hour: number
  bracket: string
  avg_price: number
  min_price: number
  max_price: number
  samples: number
}

interface ElapsedRow {
  elapsed_day: number
  bracket: string
  avg_price: number
  min_price: number
  max_price: number
  samples: number
}

export function PriceByDowHourHeatmap({ data }: { data: DowHourRow[] | undefined }) {
  const brackets = Array.from(new Set((data || []).map((d) => d.bracket))).sort()
  const [selectedBracket, setSelectedBracket] = useState<string>("")

  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Bid Prices by Day & Hour
        </h2>
        <p className="py-4 text-center text-sm text-muted-foreground">
          No price data yet — heatmap populates as signals are generated
        </p>
      </div>
    )
  }

  const activeBracket = selectedBracket || brackets[0] || ""
  const filtered = data.filter((d) => d.bracket === activeBracket)

  const lookup: Record<string, DowHourRow> = {}
  for (const r of filtered) {
    lookup[`${r.dow}-${r.hour}`] = r
  }

  const allPrices = filtered.map((d) => d.avg_price)
  const minPrice = Math.min(...allPrices)
  const maxPrice = Math.max(...allPrices)

  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
  const hours = Array.from({ length: 24 }, (_, i) => i)

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Bid Prices by Day & Hour
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Average market price by day of week and hour (UTC). Green = cheaper to buy. Red = more expensive.
          </p>
        </div>
        <select
          value={activeBracket}
          onChange={(e) => setSelectedBracket(e.target.value)}
          className="rounded border border-border bg-background px-2 py-1 text-xs"
        >
          {brackets.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr>
              <th className="py-1 pr-2 text-left text-muted-foreground" />
              {hours.map((h) => (
                <th key={h} className="px-0.5 py-1 text-center text-muted-foreground">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {days.map((day, dow) => (
              <tr key={dow}>
                <td className="py-0.5 pr-2 font-medium text-muted-foreground">{day}</td>
                {hours.map((hour) => {
                  const cell = lookup[`${dow}-${hour}`]
                  if (!cell) {
                    return (
                      <td key={hour} className="px-0.5 py-0.5">
                        <div className="rounded bg-muted/30 px-1 py-1.5 text-center text-muted-foreground/40">
                          —
                        </div>
                      </td>
                    )
                  }
                  return (
                    <td key={hour} className="px-0.5 py-0.5">
                      <div
                        className="rounded px-1 py-1.5 text-center text-white font-mono"
                        style={{ backgroundColor: heatColor(cell.avg_price, minPrice, maxPrice) }}
                        title={`${day} ${hour}:00 — avg: ${(cell.avg_price * 100).toFixed(1)}¢, min: ${(cell.min_price * 100).toFixed(1)}¢, n=${cell.samples}`}
                      >
                        {fmt(cell.avg_price * 100)}¢
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


export function PriceByElapsedDayHeatmap({ data }: { data: ElapsedRow[] | undefined }) {
  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Bid Prices by Days Since Launch
        </h2>
        <p className="py-4 text-center text-sm text-muted-foreground">
          No price data yet — heatmap populates as signals are generated
        </p>
      </div>
    )
  }

  const brackets = Array.from(new Set(data.map((d) => d.bracket))).sort()
  const days = Array.from(new Set(data.map((d) => d.elapsed_day))).sort((a, b) => a - b)

  const lookup: Record<string, ElapsedRow> = {}
  for (const r of data) {
    lookup[`${r.elapsed_day}-${r.bracket}`] = r
  }

  const allPrices = data.map((d) => d.avg_price)
  const minPrice = Math.min(...allPrices)
  const maxPrice = Math.max(...allPrices)

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Bid Prices by Days Since Auction Launch
      </h2>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">
        How bracket prices change as the auction progresses. Green = cheaper. Shows if prices are typically higher early and taper down.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="py-2 pr-3 text-left text-muted-foreground">Bracket</th>
              {days.map((d) => (
                <th key={d} className="px-1 py-2 text-center text-muted-foreground">
                  Day {d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {brackets.map((bracket) => (
              <tr key={bracket} className="border-t border-border/30">
                <td className="py-1.5 pr-3 font-medium text-xs whitespace-nowrap">{bracket}</td>
                {days.map((day) => {
                  const cell = lookup[`${day}-${bracket}`]
                  if (!cell) {
                    return (
                      <td key={day} className="px-1 py-1.5">
                        <div className="rounded bg-muted/30 px-1 py-1 text-center text-muted-foreground/40">—</div>
                      </td>
                    )
                  }
                  return (
                    <td key={day} className="px-1 py-1.5">
                      <div
                        className="rounded px-1 py-1 text-center text-white font-mono text-[10px]"
                        style={{ backgroundColor: heatColor(cell.avg_price, minPrice, maxPrice) }}
                        title={`Day ${day}, ${bracket} — avg: ${(cell.avg_price * 100).toFixed(1)}¢, n=${cell.samples}`}
                      >
                        {fmt(cell.avg_price * 100)}¢
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
