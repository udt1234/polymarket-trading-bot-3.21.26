"use client"

/**
 * Bracket Analysis card.
 *
 * Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md
 *
 * Module-id-driven. Renders generically off the API response — no per-module
 * branching here. Three sub-tables (per-bracket stats, recent vs all-time
 * comparison, allocation recommendation) plus tabs and filters.
 */
import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { CardHeadline } from "./card-headline"
import { cn } from "@/lib/utils"

interface BracketRow {
  bracket: string
  signals_count: number
  trades_count: number
  won_count: number
  events_count: number
  win_rate_pct: number
  avg_entry_price: number
  avg_roi_pct: number
  ev_per_trade_usd: number
  last_5_results: string
  annotation: "winner" | "stop" | "never_tested" | null
  trade_share_pct: number
}

interface ComparisonRow {
  bracket: string
  last_window_win_pct: number
  all_time_win_pct: number
  delta_pt: number
  trend: "improving" | "stable" | "regime_shift"
}

interface BracketResponse {
  headline: { lines: string[] }
  rows: BracketRow[]
  comparison: ComparisonRow[]
  allocation: Record<string, number>
  n_auctions: number
  data_quality: "ok" | "insufficient"
  config: { mode: string; window: string; reserve_pct: number }
}

type Mode = "all_signals" | "spike_only"
type Window = "last_5" | "last_10" | "all_time"

export function BracketAnalysisCard({ moduleId }: { moduleId: string }) {
  const [mode, setMode] = useState<Mode>("all_signals")
  const [window, setWindow] = useState<Window>("last_10")
  const [reservePct, setReservePct] = useState<number>(25)

  const url =
    `/api/modules/${moduleId}/brackets` +
    `?mode=${mode}&window=${window}&reserve_pct=${reservePct}`
  const { data, loading } = useApi<BracketResponse>(url, [mode, window, reservePct])

  const rows = data?.rows || []
  const comparison = data?.comparison || []
  const allocation = data?.allocation || {}

  return (
    <div>
      <CardHeadline
        emoji="📊"
        title="Bracket Analysis"
        lines={data?.headline?.lines || []}
      />

      <div className="rounded-lg border border-border bg-card p-4">
        {/* Filter row */}
        <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-border pb-3">
          <div className="inline-flex rounded border border-border bg-background text-xs">
            <button
              onClick={() => setMode("spike_only")}
              className={cn(
                "px-3 py-1 transition-colors",
                mode === "spike_only" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              Spike-triggered
            </button>
            <button
              onClick={() => setMode("all_signals")}
              className={cn(
                "border-l border-border px-3 py-1 transition-colors",
                mode === "all_signals" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              All signals
            </button>
          </div>

          <div className="flex items-center gap-1 text-xs">
            <span className="text-muted-foreground">Window:</span>
            <select
              value={window}
              onChange={(e) => setWindow(e.target.value as Window)}
              className="rounded border border-border bg-background px-2 py-1"
            >
              <option value="last_5">Last 5</option>
              <option value="last_10">Last 10</option>
              <option value="all_time">All time</option>
            </select>
          </div>

          <div className="ml-auto text-xs text-muted-foreground">
            N = {data?.n_auctions ?? 0}
            {data?.data_quality === "insufficient" && (
              <span className="ml-2 text-amber-400">(insufficient — need ≥5)</span>
            )}
          </div>
        </div>

        {loading && <p className="text-xs text-muted-foreground">Loading...</p>}

        {!loading && rows.length === 0 && (
          <p className="text-xs text-muted-foreground">No bracket data yet.</p>
        )}

        {/* Per-bracket stats table */}
        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5 text-left">Bracket</th>
                  <th className="px-2 py-1.5 text-right">Signals</th>
                  <th className="px-2 py-1.5 text-right">Trades</th>
                  <th className="px-2 py-1.5 text-right">Won</th>
                  <th className="px-2 py-1.5 text-right">Win%</th>
                  <th className="px-2 py-1.5 text-right">Avg Px</th>
                  <th className="px-2 py-1.5 text-right">Avg ROI</th>
                  <th className="px-2 py-1.5 text-right">EV/trade</th>
                  <th className="px-2 py-1.5 text-right">L5</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.bracket} className="border-t border-border/40">
                    <td className="px-2 py-1.5 font-medium">
                      {r.bracket}
                      {r.annotation === "winner" && <span className="ml-1 text-success" title="winner">↑</span>}
                      {r.annotation === "stop" && <span className="ml-1 text-destructive" title="stop">↓</span>}
                      {r.annotation === "never_tested" && <span className="ml-1 text-muted-foreground/60" title="never tested">·</span>}
                    </td>
                    <td className="px-2 py-1.5 text-right text-muted-foreground">{r.signals_count}</td>
                    <td className="px-2 py-1.5 text-right text-muted-foreground">{r.trades_count}</td>
                    <td className="px-2 py-1.5 text-right text-muted-foreground">
                      {r.events_count > 0 ? `${r.won_count}/${r.events_count}` : "—"}
                    </td>
                    <td className={cn(
                      "px-2 py-1.5 text-right font-medium",
                      r.win_rate_pct >= 65 ? "text-success" : r.win_rate_pct < 30 && r.events_count > 0 ? "text-destructive" : "text-foreground",
                    )}>
                      {r.events_count > 0 ? `${r.win_rate_pct}%` : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-right text-muted-foreground">
                      {r.avg_entry_price > 0 ? `${(r.avg_entry_price * 100).toFixed(1)}¢` : "—"}
                    </td>
                    <td className={cn(
                      "px-2 py-1.5 text-right",
                      r.avg_roi_pct > 0 ? "text-success" : r.avg_roi_pct < 0 ? "text-destructive" : "text-muted-foreground",
                    )}>
                      {r.avg_roi_pct !== 0 ? `${r.avg_roi_pct > 0 ? "+" : ""}${r.avg_roi_pct}%` : "—"}
                    </td>
                    <td className={cn(
                      "px-2 py-1.5 text-right",
                      r.ev_per_trade_usd > 0 ? "text-success" : r.ev_per_trade_usd < 0 ? "text-destructive" : "text-muted-foreground",
                    )}>
                      {r.ev_per_trade_usd !== 0 ? `${r.ev_per_trade_usd > 0 ? "+" : ""}$${r.ev_per_trade_usd.toFixed(2)}` : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-[10px]">{r.last_5_results || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[10px] text-muted-foreground/70">
              ↑ = win rate ≥65% AND under-traded · ↓ = negative EV (stop) · · = declared but never traded
            </p>
          </div>
        )}

        {/* Recent vs all-time comparison */}
        {comparison.length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Comparison to baseline — recent vs all-time
            </p>
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-2 py-1 text-left">Bracket</th>
                  <th className="px-2 py-1 text-right">Recent Win%</th>
                  <th className="px-2 py-1 text-right">All-time Win%</th>
                  <th className="px-2 py-1 text-right">Δ</th>
                  <th className="px-2 py-1 text-right">Trend</th>
                </tr>
              </thead>
              <tbody>
                {comparison.map((c) => (
                  <tr key={c.bracket} className="border-t border-border/40">
                    <td className="px-2 py-1 font-medium">{c.bracket}</td>
                    <td className="px-2 py-1 text-right text-muted-foreground">{c.last_window_win_pct}%</td>
                    <td className="px-2 py-1 text-right text-muted-foreground">{c.all_time_win_pct}%</td>
                    <td className={cn(
                      "px-2 py-1 text-right font-medium",
                      c.delta_pt > 0 ? "text-success" : c.delta_pt < 0 ? "text-destructive" : "text-muted-foreground",
                    )}>
                      {c.delta_pt > 0 ? "+" : ""}{c.delta_pt}pt
                    </td>
                    <td className="px-2 py-1 text-right text-muted-foreground">
                      {c.trend === "regime_shift" && <span className="text-amber-400">⚠ regime shift</span>}
                      {c.trend === "improving" && <span className="text-success">↑ improving</span>}
                      {c.trend === "stable" && "stable"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-[10px] text-muted-foreground/70">
              ⚠ regime shift = -15pt or worse (strategy may be drifting)
            </p>
          </div>
        )}

        {/* Allocation recommendation */}
        {Object.keys(allocation).length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Allocation recommendation
              </p>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <span>Reserve %:</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={5}
                  value={reservePct}
                  onChange={(e) => setReservePct(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
                  className="w-14 rounded border border-border bg-background px-1.5 py-0.5 text-right"
                />
              </div>
            </div>
            <p className="mb-2 text-[10px] text-muted-foreground/70">
              Based on EV/trade × win rate × signal count. Brackets with negative EV get 0%.
            </p>
            <div className="space-y-1">
              {Object.entries(allocation)
                .sort((a, b) => b[1] - a[1])
                .map(([bracket, pct]) => (
                  <div key={bracket} className="flex items-center gap-2 text-xs">
                    <span className={cn(
                      "w-20 font-medium",
                      bracket === "reserve" && "text-muted-foreground",
                    )}>
                      {bracket === "reserve" ? "Reserve" : bracket}
                    </span>
                    <div className="h-2 flex-1 rounded-full bg-muted">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          bracket === "reserve" ? "bg-muted-foreground/40" : "bg-primary",
                        )}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="w-10 text-right text-muted-foreground">{pct}%</span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
