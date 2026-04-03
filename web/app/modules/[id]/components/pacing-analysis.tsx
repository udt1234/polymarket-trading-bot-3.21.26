import { cn } from "@/lib/utils"
import { ArrowUpRight, ArrowDownRight, Minus } from "lucide-react"

function fmt(n: number, decimals = 1): string {
  return parseFloat(n.toFixed(decimals)).toString()
}

function heatColor(intensity: number): string {
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

export function DowHeatmap({ dowAvg }: { dowAvg: any[] | undefined }) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        DOW Averages Heatmap
      </h2>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">Historical average posts per day of the week. Greener = more posts typically. Based on recency-weighted data — recent weeks count more than older ones.</p>
      {dowAvg && Array.isArray(dowAvg) && dowAvg.length > 0 ? (
        <div className="grid grid-cols-7 gap-1.5">
          {dowAvg.map((d: any, i: number) => {
            const maxAvg = Math.max(...dowAvg.map((x: any) => x.avg || 0))
            const minAvg = Math.min(...dowAvg.map((x: any) => x.avg || 0))
            const range = maxAvg - minAvg || 1
            const intensity = ((d.avg || 0) - minAvg) / range
            return (
              <div
                key={i}
                className="rounded border border-border p-2 text-center"
                style={{ backgroundColor: heatColor(intensity) }}
              >
                <p className="text-xs font-semibold text-white">{d.day}</p>
                <p className="mt-0.5 text-lg font-bold text-white">{fmt(d.avg || 0)}</p>
                <p className="text-[10px] text-white/70">&sigma;{fmt(d.std || 0)} n={d.samples || 0}</p>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">No DOW data yet</p>
      )}
    </div>
  )
}

function hourLabel(h: number): string {
  if (h === 0) return "12AM"
  if (h === 12) return "12PM"
  return h < 12 ? `${h}AM` : `${h - 12}PM`
}

export function HourlyHeatmap({ hourlyAvg, historicalHourly }: { hourlyAvg: any[] | undefined; historicalHourly: any[] | undefined }) {
  const data = (historicalHourly && historicalHourly.length > 0) ? historicalHourly : hourlyAvg
  const isHistorical = !!(historicalHourly && historicalHourly.length > 0)

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Hourly Posts Heatmap
      </h2>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">
        Average posts per hour (UTC). {isHistorical ? "Based on years of historical data." : "Based on current auction data."}
      </p>
      {data && Array.isArray(data) && data.length > 0 ? (
        <div className="flex flex-col items-center gap-6 lg:flex-row lg:items-start lg:justify-center">
          {/* Clock face */}
          <div className="relative" style={{ width: 320, height: 320 }}>
            <svg viewBox="0 0 320 320" className="w-full h-full">
              <circle cx="160" cy="160" r="155" fill="none" stroke="hsl(var(--border))" strokeWidth="1" />
              <circle cx="160" cy="160" r="105" fill="none" stroke="hsl(var(--border))" strokeWidth="1" strokeDasharray="4 4" />
              {data.map((d: any) => {
                const maxAvg = Math.max(...data.map((x: any) => x.avg || 0))
                const minAvg = Math.min(...data.map((x: any) => x.avg || 0))
                const range = maxAvg - minAvg || 1
                const intensity = ((d.avg || 0) - minAvg) / range
                const angle = ((d.hour - 3) * 15) * (Math.PI / 180)
                const r = 130
                const x = 160 + r * Math.cos(angle)
                const y = 160 + r * Math.sin(angle)
                const size = 16 + intensity * 10
                const color = heatColor(intensity)
                return (
                  <g key={d.hour}>
                    <circle
                      cx={x} cy={y} r={size}
                      fill={color}
                      stroke={color}
                      strokeWidth="1.5"
                    />
                    <text x={x} y={y - 4} textAnchor="middle" fill="white" fontSize="8" fontWeight="bold">
                      {hourLabel(d.hour)}
                    </text>
                    <text x={x} y={y + 7} textAnchor="middle" fill="white" fontSize="10" fontWeight="bold">
                      {fmt(d.avg || 0)}
                    </text>
                  </g>
                )
              })}
              <text x="160" y="155" textAnchor="middle" fill="hsl(var(--muted-foreground))" fontSize="10">Posts/hr</text>
              <text x="160" y="170" textAnchor="middle" fill="hsl(var(--muted-foreground))" fontSize="9">(UTC)</text>
            </svg>
          </div>
          {/* Legend bar */}
          <div className="grid grid-cols-6 gap-1 lg:grid-cols-4 lg:w-48">
            {data.map((d: any) => {
              const maxAvg = Math.max(...data.map((x: any) => x.avg || 0))
              const minAvg = Math.min(...data.map((x: any) => x.avg || 0))
              const range = maxAvg - minAvg || 1
              const intensity = ((d.avg || 0) - minAvg) / range
              return (
                <div
                  key={d.hour}
                  className="rounded px-1 py-0.5 text-center text-[9px]"
                  style={{ backgroundColor: heatColor(intensity) }}
                >
                  <span className="text-white font-semibold">{hourLabel(d.hour)}</span>
                  <span className="text-white/80 ml-0.5">{fmt(d.avg || 0)}</span>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">No hourly data yet</p>
      )}
    </div>
  )
}

export function PaceAcceleration({ accel }: { accel: any }) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Pace Acceleration
      </h2>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">Is posting speeding up or slowing down compared to earlier in the period? Compares the recent hourly rate to the prior rate.</p>
      {accel ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-muted-foreground">Current Rate</p>
              <p className="text-2xl font-bold">{accel.current_rate.toFixed(2)}</p>
              <p className="text-xs text-muted-foreground">posts/hr</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Prior Rate</p>
              <p className="text-2xl font-bold">{accel.prior_rate.toFixed(2)}</p>
              <p className="text-xs text-muted-foreground">posts/hr</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {accel.momentum === "accelerating" && <ArrowUpRight className="h-6 w-6 text-success" />}
            {accel.momentum === "decelerating" && <ArrowDownRight className="h-6 w-6 text-destructive" />}
            {accel.momentum === "steady" && <Minus className="h-6 w-6 text-muted-foreground" />}
            <span className={cn(
              "text-lg font-semibold capitalize",
              accel.momentum === "accelerating" && "text-success",
              accel.momentum === "decelerating" && "text-destructive",
              accel.momentum === "steady" && "text-muted-foreground",
            )}>
              {accel.momentum}
            </span>
          </div>
          <div>
            <p className="mb-1 text-xs text-muted-foreground">Momentum</p>
            <div className="h-3 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  accel.momentum === "accelerating" ? "bg-success" :
                  accel.momentum === "decelerating" ? "bg-destructive" : "bg-muted-foreground"
                )}
                style={{
                  width: `${Math.min(100, Math.max(5, (accel.current_rate / Math.max(accel.prior_rate, 0.01)) * 50))}%`,
                }}
              />
            </div>
          </div>
        </div>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">No acceleration data yet</p>
      )}
    </div>
  )
}

export function ConfidenceBands({ bands }: { bands: any[] | undefined }) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Confidence Bands
      </h2>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">Our model's best guess at which bracket will win, ranked by probability. The wider the gap between #1 and #2, the more confident the prediction.</p>
      {bands && bands.length > 0 ? (
        <div className="space-y-4">
          <div className="rounded border border-primary/30 bg-primary/5 p-3 text-center">
            <p className="text-xs text-muted-foreground">Projected Winner</p>
            <p className="text-xl font-bold text-primary">{bands[0]?.bracket}</p>
            <p className="text-sm text-muted-foreground">
              Confidence: {fmt((bands[0]?.confidence || bands[0]?.probability || 0) * 100)}%
            </p>
          </div>
          <div className="space-y-2">
            {bands.slice(0, 3).map((b, i) => {
              const pct = b.probability * 100
              return (
                <div key={i} className="space-y-0.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium">{b.bracket}</span>
                    <span className="font-mono text-muted-foreground">{fmt(pct)}%</span>
                  </div>
                  <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${Math.min(pct * 2, 100)}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">No confidence data yet</p>
      )}
    </div>
  )
}

export function EnsembleBreakdown({ ensemble, ensembleAvg }: { ensemble: any[] | undefined; ensembleAvg: number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Ensemble Sub-Model Breakdown
      </h2>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">Four prediction models each estimate the final post count. Their outputs are blended using weights that shift as the week progresses — early week trusts history, late week trusts current pace.</p>
      {ensemble && Array.isArray(ensemble) && ensemble.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-2 text-left">Model</th>
                <th className="py-2 text-right">Projection</th>
                <th className="py-2 text-right">Weight</th>
                <th className="py-2 text-right">Contribution</th>
              </tr>
            </thead>
            <tbody>
              {ensemble.map((m: any, i: number) => (
                <tr key={i} className="border-b border-border last:border-0">
                  <td className="py-2 font-medium">{m.model}</td>
                  <td className="py-2 text-right font-mono">{fmt(m.projection || 0)}</td>
                  <td className="py-2 text-right font-mono">{fmt(m.weight || 0)}%</td>
                  <td className="py-2 text-right font-mono">{fmt(m.contribution || 0)}</td>
                </tr>
              ))}
              <tr className="bg-muted/30 font-semibold">
                <td className="py-2">Ensemble Average</td>
                <td className="py-2 text-right font-mono">{fmt(ensembleAvg || 0)}</td>
                <td className="py-2 text-right font-mono">100%</td>
                <td className="py-2 text-right font-mono">{fmt(ensembleAvg || 0)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">No ensemble data yet</p>
      )}
    </div>
  )
}
