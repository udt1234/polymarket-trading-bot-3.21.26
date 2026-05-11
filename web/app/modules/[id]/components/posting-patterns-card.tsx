"use client"

/**
 * Posting Patterns — one card, 3 tabs, plain-English headline.
 *
 * Consolidates 4 previously-separate cards (Post Timing Heatmap, Post Frequency,
 * DOW Averages Heatmap, Hourly Posts Heatmap) into a single surface keyed off
 * the same `pacing` payload. Tabs:
 *   - By Day × Hour (the DOW × hour grid — richest view, default)
 *   - By Hour-of-Day (24 cells, sum across days)
 *   - By Auction Progress (post curves by elapsed day)
 *
 * Headline is rule-derived from the pacing data — no LLM. 3-5 lines max,
 * ending with a "what to do" action when one exists.
 */
import { useState, useMemo } from "react"
import { cn } from "@/lib/utils"

const DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

const HOUR_LABELS = Array.from({ length: 24 }, (_, h) => {
  if (h === 0) return "12 AM"
  if (h === 12) return "12 PM"
  return h < 12 ? `${h} AM` : `${h - 12} PM`
})

const COLORS = { none: "#e5e7eb", low: "#4b5563", mid: "#eab308", high: "#ef4444" }
const TEXT = { none: "#9ca3af", low: "#f3f4f6", mid: "#1f2937", high: "#ffffff" }

function tier(v: number, max: number): "none" | "low" | "mid" | "high" {
  if (v <= 0 || max <= 0) return "none"
  const ratio = v / max
  if (ratio > 0.7) return "high"
  if (ratio > 0.4) return "mid"
  return "low"
}

function fmtHour(h: number): string {
  if (h === 0) return "12 AM"
  if (h === 12) return "12 PM"
  return h < 12 ? `${h} AM` : `${h - 12} PM`
}

// ─── Headline rules ──────────────────────────────────────────────────────────
function buildHeadline(grid: number[][], runningTotal: number | null, elapsedDays: number | null, totalDays: number | null): string[] {
  const dayTotals = grid.map((row) => row.reduce((a, b) => a + b, 0))
  if (dayTotals.every((t) => t === 0)) {
    return ["Not enough historical data yet — heatmap populates as posts accumulate."]
  }

  const hourSums: number[] = Array(24).fill(0)
  for (const row of grid) for (let h = 0; h < 24; h++) hourSums[h] += row[h]

  // Hottest 3-hour window across all days
  let bestStart = 0
  let bestSum = -1
  for (let start = 0; start < 22; start++) {
    const sum = hourSums[start] + hourSums[start + 1] + hourSums[start + 2]
    if (sum > bestSum) {
      bestSum = sum
      bestStart = start
    }
  }
  const peakHourly = bestSum / 3 / 7

  // Quietest 3-hour window
  let worstStart = 0
  let worstSum = Number.POSITIVE_INFINITY
  for (let start = 0; start < 22; start++) {
    const sum = hourSums[start] + hourSums[start + 1] + hourSums[start + 2]
    if (sum < worstSum) {
      worstSum = sum
      worstStart = start
    }
  }
  const quietHourly = worstSum / 3 / 7

  // Busiest / quietest day-of-week
  let busy = 0
  let quiet = 0
  for (let i = 1; i < 7; i++) {
    if (dayTotals[i] > dayTotals[busy]) busy = i
    if (dayTotals[i] < dayTotals[quiet]) quiet = i
  }
  const avgPerDay = dayTotals.reduce((a, b) => a + b, 0) / 7

  const lines: string[] = []
  lines.push(`Averages ~${avgPerDay.toFixed(0)} posts/day. Hottest: ${DOWS[busy]} ${fmtHour(bestStart)}–${fmtHour(bestStart + 3)} ET (~${peakHourly.toFixed(1)}/hr).`)
  lines.push(`Quietest: ${DOWS[quiet]} ${fmtHour(worstStart)}–${fmtHour(worstStart + 3)} ET (~${quietHourly.toFixed(1)}/hr).`)

  // Live-auction pace comparison (if we have elapsed + remaining days)
  if (runningTotal != null && elapsedDays != null && totalDays != null && elapsedDays > 0.1 && totalDays > 0) {
    const expectedFull = avgPerDay * totalDays
    const projected = (runningTotal / elapsedDays) * totalDays
    if (expectedFull > 0) {
      const deltaPct = ((projected - expectedFull) / expectedFull) * 100
      if (Math.abs(deltaPct) >= 8) {
        const direction = deltaPct > 0 ? "hotter" : "cooler"
        lines.push(`→ Current auction running ${Math.abs(deltaPct).toFixed(0)}% ${direction} than his typical ${totalDays.toFixed(0)}-day pace (${projected.toFixed(0)} vs ${expectedFull.toFixed(0)} projected).`)
      } else {
        lines.push(`→ Current auction tracking his typical ${totalDays.toFixed(0)}-day pace (~${projected.toFixed(0)} posts projected).`)
      }
    }
  }

  return lines
}

// ─── DOW × Hour grid ─────────────────────────────────────────────────────────
function DowHourGrid({ grid, max }: { grid: number[][]; max: number }) {
  return (
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
  )
}

// ─── Hour-of-Day strip (24 cells summed across DOW) ──────────────────────────
function HourOfDayStrip({ grid, max }: { grid: number[][]; max: number }) {
  const hourSums: number[] = Array(24).fill(0)
  for (const row of grid) for (let h = 0; h < 24; h++) hourSums[h] += row[h]
  const hourAvg = hourSums.map((s) => s / 7) // avg posts/hour at this hour, across all DOWs
  const hourMax = Math.max(...hourAvg, 0.001)

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Posts per hour at each hour-of-day, averaged across all days of week.
      </p>
      <div className="overflow-x-auto">
        <div className="flex gap-[2px]" style={{ minWidth: "640px" }}>
          {hourAvg.map((v, h) => {
            const t = tier(v, hourMax)
            return (
              <div key={h} className="flex flex-col items-center" style={{ width: `${100 / 24}%` }}>
                <div
                  className="w-full rounded-[2px] flex items-end justify-center"
                  style={{
                    backgroundColor: COLORS[t],
                    color: TEXT[t],
                    height: `${Math.max(20, (v / hourMax) * 80)}px`,
                  }}
                  title={`${HOUR_LABELS[h]} — ${v.toFixed(2)} avg posts/hr`}
                >
                  <span className="text-[9px] font-semibold leading-tight pb-0.5">
                    {v >= 1 ? v.toFixed(1) : v.toFixed(2)}
                  </span>
                </div>
                <div className="mt-1 text-[9px] text-muted-foreground whitespace-nowrap">{HOUR_LABELS[h]}</div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ─── Auction-progress view ───────────────────────────────────────────────────
// Posts per day-of-auction (Day 0, Day 1, ...) from historical_daily totals.
function AuctionProgressView({
  historicalDaily,
  runningTotal,
  elapsedDays,
  totalDays,
}: {
  historicalDaily: any[] | undefined
  runningTotal: number | null
  elapsedDays: number | null
  totalDays: number | null
}) {
  // historical_daily is the per-elapsed-day historical avg from the pacing endpoint.
  // Shape: [{ elapsed_day: 0, avg_posts: 18.4, samples: 12 }, ...]
  const rows = (historicalDaily || []).slice().sort((a: any, b: any) => (a.elapsed_day ?? 0) - (b.elapsed_day ?? 0))
  if (rows.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        No auction-progress data yet — populates as auctions complete.
      </p>
    )
  }
  const max = Math.max(...rows.map((r: any) => r.avg_posts || 0), 0.001)
  let cumulative = 0
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Average posts per day of the auction (Day 0 = open). Bars show daily count; the running total in parentheses is cumulative.
      </p>
      <div className="space-y-1.5">
        {rows.map((r: any) => {
          const v = r.avg_posts || 0
          cumulative += v
          const t = tier(v, max)
          return (
            <div key={r.elapsed_day} className="flex items-center gap-3 text-xs">
              <span className="w-14 font-medium text-muted-foreground">Day {r.elapsed_day}</span>
              <div className="flex-1 h-5 rounded bg-muted relative overflow-hidden">
                <div
                  className="h-full rounded"
                  style={{ backgroundColor: COLORS[t], width: `${(v / max) * 100}%` }}
                />
                <span
                  className="absolute inset-0 flex items-center px-2 text-[10px] font-semibold"
                  style={{ color: tier(v, max) === "high" ? "#fff" : "#374151" }}
                >
                  {v.toFixed(1)} posts/day
                  <span className="ml-2 text-muted-foreground/80">(cum {cumulative.toFixed(0)})</span>
                </span>
              </div>
              <span className="w-12 text-right text-[10px] text-muted-foreground">n={r.samples || 0}</span>
            </div>
          )
        })}
      </div>
      {runningTotal != null && elapsedDays != null && totalDays != null && elapsedDays > 0 && (
        <div className="mt-3 rounded border border-border/60 bg-muted/30 px-3 py-2 text-xs">
          <span className="font-semibold text-foreground">Current auction: </span>
          <span className="text-muted-foreground">
            {runningTotal} posts in {elapsedDays.toFixed(1)} days
            {totalDays > elapsedDays && ` (${(totalDays - elapsedDays).toFixed(1)} days left)`}.
          </span>
        </div>
      )}
    </div>
  )
}

// ─── Card shell ──────────────────────────────────────────────────────────────
type Tab = "dow_hour" | "hour" | "progress"

export function PostingPatternsCard({ pacing }: { pacing: any }) {
  const [tab, setTab] = useState<Tab>("dow_hour")

  const { grid, max } = useMemo(() => {
    const grid: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0))
    let max = 0
    for (const d of pacing?.dow_hour_heatmap || []) {
      if (d.dow >= 0 && d.dow < 7 && d.hour >= 0 && d.hour < 24) {
        grid[d.dow][d.hour] = d.count
        if (d.count > max) max = d.count
      }
    }
    return { grid, max }
  }, [pacing?.dow_hour_heatmap])

  const headline = useMemo(
    () => buildHeadline(grid, pacing?.running_total ?? null, pacing?.elapsed_days ?? null, pacing?.total_days ?? null),
    [grid, pacing?.running_total, pacing?.elapsed_days, pacing?.total_days],
  )

  return (
    <div>
      {/* Headline above the box */}
      <div className="mb-2 px-1 text-sm leading-relaxed">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          📊 Posting Patterns
        </div>
        {headline.map((line, i) => (
          <p key={i} className={cn("text-foreground/90", line.startsWith("→") && "font-medium text-foreground")}>
            {line}
          </p>
        ))}
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        {/* Tabs */}
        <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-border pb-3">
          <div className="inline-flex rounded border border-border bg-background text-xs">
            <button
              onClick={() => setTab("dow_hour")}
              className={cn(
                "px-3 py-1 transition-colors",
                tab === "dow_hour" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              By Day × Hour
            </button>
            <button
              onClick={() => setTab("hour")}
              className={cn(
                "border-l border-border px-3 py-1 transition-colors",
                tab === "hour" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              By Hour-of-Day
            </button>
            <button
              onClick={() => setTab("progress")}
              className={cn(
                "border-l border-border px-3 py-1 transition-colors",
                tab === "progress" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              By Auction Progress
            </button>
          </div>

          <div className="ml-auto inline-flex items-center gap-2 text-[10px] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS.high }} /> High
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS.mid }} /> Mid
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS.low }} /> Low
            </span>
          </div>
        </div>

        {tab === "dow_hour" && <DowHourGrid grid={grid} max={max} />}
        {tab === "hour" && <HourOfDayStrip grid={grid} max={max} />}
        {tab === "progress" && (
          <AuctionProgressView
            historicalDaily={pacing?.historical_daily}
            runningTotal={pacing?.running_total ?? null}
            elapsedDays={pacing?.elapsed_days ?? null}
            totalDays={pacing?.total_days ?? null}
          />
        )}
      </div>
    </div>
  )
}
