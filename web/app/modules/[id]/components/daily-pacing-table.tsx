"use client"

import { useState } from "react"
import { formatDate, cn } from "@/lib/utils"
import { AreaChart, Area, LineChart, Line, ComposedChart, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

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

  // Chart data
  const chartData = dailyTable.map((row: any, i: number) => {
    const expected = Math.round(dailyRate * (i + 1))
    const actual = (!row.is_future) ? (row.running_total ?? null) : null
    return {
      label: row.day?.slice(0, 3) || "",
      actual,
      expected,
      projected: paceValues[i],
    }
  })

  const lastActual = chartData.filter((d: any) => d.actual != null)
  const isAhead = lastActual.length > 0 && lastActual[lastActual.length - 1].actual >= lastActual[lastActual.length - 1].expected

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Pacing
        </h2>
        <select
          value={selectedStrategy}
          onChange={(e) => setSelectedStrategy(e.target.value)}
          className="rounded border border-border bg-background px-2 py-1 text-xs"
        >
          {strategyOptions.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label} ({Math.round(s.projection)})
            </option>
          ))}
        </select>
      </div>
      {dailyTable.length > 0 ? (
        <div className="flex flex-col xl:flex-row">
          {/* Table — 60% */}
          <div className="xl:w-[60%] overflow-x-auto xl:border-r xl:border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-2 py-2 text-left whitespace-nowrap">Date</th>
                  <th className="px-2 py-2 text-left">Day</th>
                  <th className="px-2 py-2 text-right">Daily</th>
                  <th className="px-2 py-2 text-right">Running</th>
                  <th className="px-2 py-2 text-right">Proj</th>
                  <th className="px-2 py-2 text-right">DOW</th>
                  <th className="px-2 py-2 text-right">Dev</th>
                  <th className="px-2 py-2 text-center">St.</th>
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
                      <td className="px-2 py-2 whitespace-nowrap">{formatDate(row.date)}</td>
                      <td className="px-2 py-2">{row.day}</td>
                      <td className="px-2 py-2 text-right">
                        {row.is_future
                          ? <span className="text-muted-foreground italic" title="Projected from DOW avg">~{(row.dow_avg ?? 0).toFixed(0)}</span>
                          : (row.daily_posts ?? "—")}
                      </td>
                      <td className="px-2 py-2 text-right">
                        {row.is_future
                          ? <span className="text-muted-foreground italic">—</span>
                          : (row.running_total ?? "—")}
                      </td>
                      <td className="px-2 py-2 text-right font-mono">
                        {showPace ? (
                          <span className="text-primary font-semibold">{pace}</span>
                        ) : (
                          <span className="text-muted-foreground">{pace}</span>
                        )}
                      </td>
                      <td className="px-2 py-2 text-right">{(row.dow_avg ?? 0).toFixed(1)}</td>
                      <td className={cn(
                        "px-2 py-2 text-right font-mono",
                        row.status === "ahead" && "text-success",
                        row.status === "behind" && "text-destructive",
                        row.status === "on_pace" && "text-muted-foreground",
                      )}>
                        {row.deviation != null ? `${row.deviation > 0 ? "+" : ""}${row.deviation.toFixed(1)}` : "—"}
                      </td>
                      <td className="px-2 py-2 text-center">
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

          {/* Chart — 40% */}
          <div className="xl:w-[40%] p-4 flex flex-col">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
              Pacing vs Expected
            </h3>
            <div className="flex-1 min-h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="pacingAheadGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(142, 71%, 45%)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="hsl(142, 71%, 45%)" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="pacingBehindGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(0, 84%, 60%)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="hsl(0, 84%, 60%)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
                  <YAxis tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
                  <Tooltip
                    contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 11 }}
                    formatter={(value: any, name: string) => [value, name === "actual" ? "Actual" : name === "expected" ? "Expected" : "Projected"]}
                  />
                  {/* Expected: dashed grey line */}
                  <Line type="monotone" dataKey="expected" stroke="hsl(215, 20%, 55%)" strokeDasharray="5 5" strokeWidth={1.5} dot={false} />
                  {/* Actual: solid line with fill */}
                  <Area
                    type="monotone"
                    dataKey="actual"
                    stroke={isAhead ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)"}
                    fill={isAhead ? "url(#pacingAheadGrad)" : "url(#pacingBehindGrad)"}
                    strokeWidth={2}
                    dot={{ r: 2, fill: isAhead ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)" }}
                    connectNulls={false}
                  />
                  {/* Projected trend: purple dashed */}
                  <Line type="monotone" dataKey="projected" stroke="hsl(280, 60%, 60%)" strokeDasharray="3 3" strokeWidth={1} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="flex gap-4 mt-2 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="inline-block w-3 h-0.5 rounded" style={{ background: isAhead ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)" }} />
                Actual
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-3 border-t border-dashed" style={{ borderColor: "hsl(215, 20%, 55%)" }} />
                Expected
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-3 border-t border-dashed" style={{ borderColor: "hsl(280, 60%, 60%)" }} />
                Projected
              </span>
            </div>
          </div>
        </div>
      ) : (
        <p className="px-6 py-8 text-center text-sm text-muted-foreground">No pacing data yet</p>
      )}
    </div>
  )
}
