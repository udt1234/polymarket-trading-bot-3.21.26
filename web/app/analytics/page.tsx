"use client"

import { useApi } from "@/lib/hooks"
import { formatCurrency, cn } from "@/lib/utils"
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts"

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("rounded-lg border border-border bg-card p-4", className)}>{children}</div>
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 text-lg font-semibold">{children}</h2>
}

function Empty() {
  return <p className="text-sm text-muted-foreground">No data yet — analytics will populate as the engine runs</p>
}

export default function AnalyticsPage() {
  const { data: summary } = useApi<any>("/api/analytics/summary")
  const { data: roi } = useApi<any>("/api/analytics/roi")
  const { data: drawdown } = useApi<any[]>("/api/analytics/drawdown")
  const { data: edgeDecay } = useApi<any[]>("/api/analytics/edge-decay")
  const { data: fillRate } = useApi<any>("/api/analytics/fill-rate")
  const { data: bracketHeatmap } = useApi<any[]>("/api/analytics/bracket-heatmap")
  const { data: regime } = useApi<any>("/api/analytics/regime")
  const { data: pnlAttribution } = useApi<any>("/api/analytics/pnl-attribution")
  const { data: monteCarlo } = useApi<any>("/api/analytics/monte-carlo")
  const { data: walkForward } = useApi<any>("/api/analytics/walk-forward")
  const { data: alertHistory } = useApi<any[]>("/api/analytics/alert-history")
  const { data: calibration } = useApi<any[]>("/api/analytics/calibration")

  const summaryCards = [
    { label: "Sharpe Ratio", value: summary?.sharpe?.toFixed(3) },
    { label: "Sortino Ratio", value: summary?.sortino?.toFixed(3) },
    { label: "Max Drawdown", value: summary?.max_drawdown != null ? `${(summary.max_drawdown * 100).toFixed(2)}%` : null },
    { label: "Calmar Ratio", value: summary?.calmar?.toFixed(3) },
    { label: "Profit Factor", value: summary?.profit_factor?.toFixed(3) },
    { label: "Total Days", value: summary?.total_days?.toString() },
  ]

  const roiCards = [
    { label: "Daily ROI", value: roi?.daily != null ? `${(roi.daily * 100).toFixed(2)}%` : null },
    { label: "Weekly ROI", value: roi?.weekly != null ? `${(roi.weekly * 100).toFixed(2)}%` : null },
    { label: "Monthly ROI", value: roi?.monthly != null ? `${(roi.monthly * 100).toFixed(2)}%` : null },
    { label: "All-time ROI", value: roi?.all_time != null ? `${(roi.all_time * 100).toFixed(2)}%` : null },
  ]

  const maxDd = drawdown?.reduce((min: any, d: any) => (d.drawdown < (min?.drawdown ?? 0) ? d : min), drawdown[0])

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Analytics</h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {summaryCards.map((m) => (
          <Card key={m.label}>
            <p className="text-xs text-muted-foreground">{m.label}</p>
            <p className="text-xl font-bold">{m.value ?? "—"}</p>
          </Card>
        ))}
      </div>

      {/* ROI Cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {roiCards.map((m) => (
          <Card key={m.label}>
            <p className="text-xs text-muted-foreground">{m.label}</p>
            <p className={cn("text-xl font-bold", m.value && parseFloat(m.value) >= 0 ? "text-green-400" : "text-red-400")}>
              {m.value ?? "—"}
            </p>
          </Card>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Drawdown Chart */}
        <Card>
          <SectionTitle>Drawdown</SectionTitle>
          {drawdown && drawdown.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={drawdown}>
                <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="#555" />
                <YAxis tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} stroke="#555" />
                <Tooltip formatter={(v: number) => `${(v * 100).toFixed(2)}%`} contentStyle={{ background: "#1a1a2e", border: "1px solid #333" }} />
                <Area type="monotone" dataKey="drawdown" stroke="#ef4444" fill="#ef444433" />
                {maxDd && <ReferenceLine y={maxDd.drawdown} stroke="#f97316" strokeDasharray="4 4" label={{ value: `Max: ${(maxDd.drawdown * 100).toFixed(2)}%`, fill: "#f97316", fontSize: 10 }} />}
              </AreaChart>
            </ResponsiveContainer>
          ) : <Empty />}
        </Card>

        {/* Edge Decay Chart */}
        <Card>
          <SectionTitle>Edge Decay</SectionTitle>
          {edgeDecay && edgeDecay.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={edgeDecay}>
                <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="#555" />
                <YAxis tick={{ fontSize: 10 }} stroke="#555" />
                <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid #333" }} />
                <Line type="monotone" dataKey="avg_edge" stroke="#3b82f6" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          ) : <Empty />}
        </Card>
      </div>

      {/* Fill Rate + Regime + Walk-Forward */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <SectionTitle>Fill Rate</SectionTitle>
          {fillRate ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">Total Orders</span><span className="font-medium">{fillRate.total_orders}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Fill Rate</span><span className="font-medium">{(fillRate.fill_rate * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Avg Slippage</span><span className="font-medium">{fillRate.avg_slippage?.toFixed(4)}</span></div>
            </div>
          ) : <Empty />}
        </Card>

        <Card>
          <SectionTitle>Regime Indicator</SectionTitle>
          {regime ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">Regime</span><span className="font-semibold">{regime.label}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Z-Score</span><span>{regime.zscore?.toFixed(3)}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Trend</span><span>{regime.trend}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Volatility</span><span>{regime.volatility?.toFixed(4)}</span></div>
            </div>
          ) : <Empty />}
        </Card>

        <Card>
          <SectionTitle>Walk-Forward Health</SectionTitle>
          {walkForward ? (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <span className={cn("h-3 w-3 rounded-full", walkForward.status === "pass" ? "bg-green-400" : "bg-red-400")} />
                <span className="font-semibold capitalize">{walkForward.status}</span>
              </div>
              {walkForward.last_run && <p className="text-muted-foreground">Last run: {walkForward.last_run}</p>}
              {walkForward.message && <p className="text-muted-foreground">{walkForward.message}</p>}
            </div>
          ) : <Empty />}
        </Card>
      </div>

      {/* Bracket Heatmap */}
      <Card>
        <SectionTitle>Bracket Heatmap</SectionTitle>
        {bracketHeatmap && bracketHeatmap.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-2 pr-4">Bracket</th>
                  <th className="py-2 pr-4">Signals</th>
                  <th className="py-2 pr-4">Win Rate</th>
                  <th className="py-2 pr-4">Avg Edge</th>
                  <th className="py-2">Total PnL</th>
                </tr>
              </thead>
              <tbody>
                {bracketHeatmap.map((row: any) => (
                  <tr key={row.bracket} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-4 font-medium">{row.bracket}</td>
                    <td className="py-2 pr-4">{row.signal_count}</td>
                    <td className={cn("py-2 pr-4", row.win_rate >= 0.5 ? "text-green-400" : "text-red-400")}>
                      {(row.win_rate * 100).toFixed(1)}%
                    </td>
                    <td className="py-2 pr-4">{row.avg_edge?.toFixed(4)}</td>
                    <td className={cn("py-2 font-medium", row.total_pnl >= 0 ? "text-green-400" : "text-red-400")}>
                      {formatCurrency(row.total_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty />}
      </Card>

      {/* PnL Attribution + Monte Carlo */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <SectionTitle>PnL Attribution</SectionTitle>
          {pnlAttribution ? (
            <div className="space-y-4">
              {pnlAttribution.by_module && (
                <div>
                  <h3 className="mb-2 text-sm font-medium text-muted-foreground">By Module</h3>
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-border text-left text-muted-foreground"><th className="py-1">Module</th><th className="py-1 text-right">PnL</th></tr></thead>
                    <tbody>
                      {pnlAttribution.by_module.map((r: any) => (
                        <tr key={r.module} className="border-b border-border/50 last:border-0">
                          <td className="py-1">{r.module}</td>
                          <td className={cn("py-1 text-right font-medium", r.pnl >= 0 ? "text-green-400" : "text-red-400")}>{formatCurrency(r.pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {pnlAttribution.by_bracket && (
                <div>
                  <h3 className="mb-2 text-sm font-medium text-muted-foreground">By Bracket</h3>
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-border text-left text-muted-foreground"><th className="py-1">Bracket</th><th className="py-1 text-right">PnL</th></tr></thead>
                    <tbody>
                      {pnlAttribution.by_bracket.map((r: any) => (
                        <tr key={r.bracket} className="border-b border-border/50 last:border-0">
                          <td className="py-1">{r.bracket}</td>
                          <td className={cn("py-1 text-right font-medium", r.pnl >= 0 ? "text-green-400" : "text-red-400")}>{formatCurrency(r.pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : <Empty />}
        </Card>

        <Card>
          <SectionTitle>Monte Carlo Projections</SectionTitle>
          {monteCarlo ? (
            <div className="space-y-2 text-sm">
              {[
                { label: "5th Percentile", key: "p5" },
                { label: "25th Percentile", key: "p25" },
                { label: "50th Percentile (Median)", key: "p50" },
                { label: "75th Percentile", key: "p75" },
                { label: "95th Percentile", key: "p95" },
              ].map((p) => (
                <div key={p.key} className="flex justify-between">
                  <span className="text-muted-foreground">{p.label}</span>
                  <span className={cn("font-medium", monteCarlo[p.key] >= 0 ? "text-green-400" : "text-red-400")}>
                    {formatCurrency(monteCarlo[p.key])}
                  </span>
                </div>
              ))}
            </div>
          ) : <Empty />}
        </Card>
      </div>

      {/* Alert History + Calibration Log */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <SectionTitle>Alert History</SectionTitle>
          {alertHistory && alertHistory.length > 0 ? (
            <div className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {alertHistory.map((a: any, i: number) => (
                <div key={i} className="flex items-start gap-2 border-b border-border/50 py-1.5 last:border-0">
                  <span className={cn(
                    "mt-0.5 h-2 w-2 shrink-0 rounded-full",
                    a.severity === "critical" ? "bg-red-500" : a.severity === "warning" ? "bg-yellow-500" : "bg-blue-500"
                  )} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{a.message}</p>
                    <p className="text-xs text-muted-foreground">{a.timestamp}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : <Empty />}
        </Card>

        <Card>
          <SectionTitle>Calibration Log ({calibration?.length || 0} entries)</SectionTitle>
          {calibration && calibration.length > 0 ? (
            <div className="max-h-64 overflow-y-auto text-sm">
              {calibration.slice(0, 20).map((c: any, i: number) => (
                <div key={i} className="flex justify-between border-b border-border py-1.5 last:border-0">
                  <span>{c.bracket}</span>
                  <span>Pred: {c.predicted_prob?.toFixed(3)}</span>
                  <span>Brier: {c.brier_score?.toFixed(4) ?? "pending"}</span>
                </div>
              ))}
            </div>
          ) : <Empty />}
        </Card>
      </div>
    </div>
  )
}
