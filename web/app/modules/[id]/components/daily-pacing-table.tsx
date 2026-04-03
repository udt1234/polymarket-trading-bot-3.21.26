"use client"

import { useState } from "react"
import { formatDate, cn } from "@/lib/utils"

interface PacingModel {
  model: string
  projection: number
  weight: number
  contribution: number
}

export function DailyPacingTable({ pacing }: { pacing: any }) {
  const ensembleBreakdown = (pacing?.ensemble_breakdown || []) as PacingModel[]
  const ensembleAvg = pacing?.ensemble_avg || 0
  const totalDays = pacing?.total_days || 7
  const dailyTable = pacing?.daily_table || []

  const strategyOptions = [
    { value: "ensemble", label: "Ensemble Avg", projection: ensembleAvg },
    ...ensembleBreakdown.map((m) => ({
      value: m.model.toLowerCase().replace(/\s+/g, "_"),
      label: m.model,
      projection: m.projection,
    })),
  ]

  const [selectedStrategy, setSelectedStrategy] = useState("ensemble")
  const activeStrategy = strategyOptions.find((s) => s.value === selectedStrategy) || strategyOptions[0]
  const projectedTotal = activeStrategy?.projection || ensembleAvg

  const dailyRate = totalDays > 0 ? projectedTotal / totalDays : 0

  const lastActualIdx = dailyTable.findLastIndex((r: any) => !r.is_future && r.daily_posts != null)
  const lastRunningTotal = lastActualIdx >= 0 ? (dailyTable[lastActualIdx]?.running_total || 0) : 0

  let cumulativePace = 0
  const paceValues = dailyTable.map((row: any, i: number) => {
    if (!row.is_future && !row.is_today) {
      cumulativePace += (row.daily_posts ?? 0)
      return cumulativePace
    }
    if (row.is_today) {
      cumulativePace = row.running_total ?? (cumulativePace + dailyRate)
      return Math.round(cumulativePace)
    }
    const dowWeight = row.dow_weight || 0
    const overallDailyAvg = totalDays > 0 ? projectedTotal / totalDays : 0
    const dayProjection = overallDailyAvg * (dowWeight > 0 ? dowWeight : 1)
    cumulativePace += dayProjection
    return Math.round(cumulativePace)
  })

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-6 py-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Daily Pacing
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">Day-by-day breakdown. Pacing column shows projected cumulative total using the selected strategy.</p>
      </div>
      {dailyTable.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-4 py-2 text-left">Date</th>
                <th className="px-4 py-2 text-left">Day</th>
                <th className="px-4 py-2 text-right">Daily Posts</th>
                <th className="px-4 py-2 text-right">Running Total</th>
                <th className="px-4 py-2 text-right">
                  <select
                    value={selectedStrategy}
                    onChange={(e) => setSelectedStrategy(e.target.value)}
                    className="rounded border border-border bg-background px-1.5 py-0.5 text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground"
                  >
                    {strategyOptions.map((s) => (
                      <option key={s.value} value={s.value}>
                        Pace: {s.label} ({Math.round(s.projection)})
                      </option>
                    ))}
                  </select>
                </th>
                <th className="px-4 py-2 text-right">DOW Avg</th>
                <th className="px-4 py-2 text-right">Deviation</th>
                <th className="px-4 py-2 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {dailyTable.map((row: any, i: number) => {
                const pace = paceValues[i]
                const showPace = row.is_today || row.is_future
                return (
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
                    <td className="px-4 py-2 text-right font-mono">
                      {showPace ? (
                        <span className="text-primary font-semibold">{pace}</span>
                      ) : (
                        <span className="text-muted-foreground">{pace}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">{(row.dow_avg ?? 0).toFixed(1)}</td>
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
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-6 py-8 text-center text-sm text-muted-foreground">No pacing data yet</p>
      )}
    </div>
  )
}
