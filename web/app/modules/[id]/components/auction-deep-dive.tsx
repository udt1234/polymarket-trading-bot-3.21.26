"use client"

import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { formatCurrency, formatDate, cn } from "@/lib/utils"
import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight } from "lucide-react"

function fmt(n: number, d = 1) { return parseFloat(n.toFixed(d)).toString() }
function hourLabel(h: number) { return h === 0 ? "12AM" : h === 12 ? "12PM" : h < 12 ? `${h}AM` : `${h-12}PM` }

const TABS = ["Post History", "Price History", "News & Signals", "Bot Decisions"] as const
type Tab = typeof TABS[number]

function Pagination({ page, total, perPage, onPage }: { page: number; total: number; perPage: number; onPage: (p: number) => void }) {
  const pages = Math.ceil(total / perPage)
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-muted-foreground">
      <span>{total.toLocaleString()} total | Page {page} of {pages}</span>
      <div className="flex items-center gap-1">
        <button onClick={() => onPage(Math.max(1, page - 1))} disabled={page <= 1}
          className="rounded border border-border p-1 hover:bg-accent disabled:opacity-30">
          <ChevronLeft className="h-3 w-3" />
        </button>
        <button onClick={() => onPage(Math.min(pages, page + 1))} disabled={page >= pages}
          className="rounded border border-border p-1 hover:bg-accent disabled:opacity-30">
          <ChevronRight className="h-3 w-3" />
        </button>
      </div>
    </div>
  )
}

function PostHistoryTab({ moduleId }: { moduleId: string }) {
  const [page, setPage] = useState(1)
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const params = `page=${page}&per_page=50${dateFrom ? `&date_from=${dateFrom}` : ""}${dateTo ? `&date_to=${dateTo}` : ""}`
  const { data } = useApi<any>(`/api/modules/${moduleId}/deep-dive/posts?${params}`, [page, dateFrom, dateTo])

  return (
    <div>
      <div className="flex gap-2 px-4 py-2 border-b border-border">
        <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1) }}
          className="rounded border border-border bg-background px-2 py-1 text-xs" placeholder="From" />
        <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1) }}
          className="rounded border border-border bg-background px-2 py-1 text-xs" placeholder="To" />
        {(dateFrom || dateTo) && (
          <button onClick={() => { setDateFrom(""); setDateTo(""); setPage(1) }}
            className="text-xs text-primary hover:underline">Clear</button>
        )}
      </div>
      <div className="max-h-96 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border text-muted-foreground">
              <th className="px-4 py-1.5 text-left">Date</th>
              <th className="px-4 py-1.5 text-left">Hour</th>
              <th className="px-4 py-1.5 text-left">DOW</th>
              <th className="px-4 py-1.5 text-right">Posts</th>
            </tr>
          </thead>
          <tbody>
            {(data?.data || []).map((r: any, i: number) => (
              <tr key={i} className="border-b border-border/30 hover:bg-accent/30">
                <td className="px-4 py-1">{r.date}</td>
                <td className="px-4 py-1">{hourLabel(r.hour)}</td>
                <td className="px-4 py-1">{["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][r.dow] || r.dow}</td>
                <td className="px-4 py-1 text-right font-mono font-medium">{r.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} total={data?.total || 0} perPage={50} onPage={setPage} />
    </div>
  )
}

function PriceHistoryTab({ moduleId }: { moduleId: string }) {
  const [page, setPage] = useState(1)
  const [bracket, setBracket] = useState("")
  const params = `page=${page}&per_page=50${bracket ? `&bracket=${bracket}` : ""}`
  const { data } = useApi<any>(`/api/modules/${moduleId}/deep-dive/prices?${params}`, [page, bracket])

  const brackets = Array.from(new Set((data?.data || []).map((r: any) => r.bracket))).sort()

  return (
    <div>
      <div className="flex gap-2 px-4 py-2 border-b border-border">
        <select value={bracket} onChange={(e) => { setBracket(e.target.value); setPage(1) }}
          className="rounded border border-border bg-background px-2 py-1 text-xs">
          <option value="">All brackets</option>
          {brackets.map((b: any) => <option key={b} value={b}>{b}</option>)}
        </select>
      </div>
      <div className="max-h-96 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border text-muted-foreground">
              <th className="px-4 py-1.5 text-left">Time</th>
              <th className="px-4 py-1.5 text-left">Bracket</th>
              <th className="px-4 py-1.5 text-right">Price</th>
              <th className="px-4 py-1.5 text-left">DOW</th>
              <th className="px-4 py-1.5 text-right">Hour</th>
              <th className="px-4 py-1.5 text-right">Elapsed</th>
            </tr>
          </thead>
          <tbody>
            {(data?.data || []).map((r: any, i: number) => (
              <tr key={i} className="border-b border-border/30 hover:bg-accent/30">
                <td className="px-4 py-1 text-muted-foreground">{r.snapshot_hour?.slice(0, 16)}</td>
                <td className="px-4 py-1 font-medium">{r.bracket}</td>
                <td className="px-4 py-1 text-right font-mono">{fmt(r.price * 100)}c</td>
                <td className="px-4 py-1">{["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][r.dow]}</td>
                <td className="px-4 py-1 text-right">{hourLabel(r.hour_of_day)}</td>
                <td className="px-4 py-1 text-right">{r.elapsed_days != null ? `Day ${Math.floor(r.elapsed_days)}` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} total={data?.total || 0} perPage={50} onPage={setPage} />
    </div>
  )
}

function SignalsTab({ moduleId }: { moduleId: string }) {
  const [page, setPage] = useState(1)
  const { data } = useApi<any>(`/api/modules/${moduleId}/deep-dive/signals?page=${page}&per_page=30`, [page])

  return (
    <div>
      <div className="max-h-96 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border text-muted-foreground">
              <th className="px-3 py-1.5 text-left">Time</th>
              <th className="px-3 py-1.5 text-left">Bracket</th>
              <th className="px-3 py-1.5 text-right">Model</th>
              <th className="px-3 py-1.5 text-right">Market</th>
              <th className="px-3 py-1.5 text-right">Edge</th>
              <th className="px-3 py-1.5 text-right">Kelly</th>
              <th className="px-3 py-1.5 text-center">Action</th>
              <th className="px-3 py-1.5 text-left">Context</th>
            </tr>
          </thead>
          <tbody>
            {(data?.data || []).map((s: any, i: number) => {
              const meta = s.metadata || {}
              return (
                <tr key={i} className="border-b border-border/30 hover:bg-accent/30">
                  <td className="px-3 py-1 text-muted-foreground">{s.created_at?.slice(0, 16)}</td>
                  <td className="px-3 py-1 font-medium">{s.bracket}</td>
                  <td className="px-3 py-1 text-right font-mono">{fmt((s.model_prob || 0) * 100)}%</td>
                  <td className="px-3 py-1 text-right font-mono">{fmt((s.market_price || 0) * 100)}c</td>
                  <td className={cn("px-3 py-1 text-right font-mono",
                    (s.edge || 0) > 0 ? "text-success" : "text-destructive"
                  )}>{fmt((s.edge || 0) * 100, 2)}%</td>
                  <td className="px-3 py-1 text-right font-mono">{fmt((s.kelly_pct || 0) * 100)}%</td>
                  <td className="px-3 py-1 text-center">
                    <span className={cn("rounded px-1.5 py-0.5 text-[9px] font-medium",
                      s.approved ? "bg-success/20 text-success" : "bg-destructive/20 text-destructive"
                    )}>{s.approved ? "BUY" : s.rejection_reason || "PASS"}</span>
                  </td>
                  <td className="px-3 py-1 text-[10px] text-muted-foreground max-w-[200px] truncate">
                    {meta.regime && `${meta.regime} `}
                    {meta.momentum && `${meta.momentum} `}
                    {meta.signal_mod && `mod:${fmt(meta.signal_mod, 2)}`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Pagination page={page} total={data?.total || 0} perPage={30} onPage={setPage} />
    </div>
  )
}

function DecisionsTab({ moduleId }: { moduleId: string }) {
  const [page, setPage] = useState(1)
  const { data } = useApi<any>(`/api/modules/${moduleId}/deep-dive/decisions?page=${page}&per_page=30`, [page])

  return (
    <div>
      <div className="max-h-96 overflow-y-auto">
        {/* Trades */}
        <p className="px-4 py-2 text-xs font-semibold text-muted-foreground uppercase border-b border-border">
          Trade Log ({data?.trades?.total || 0})
        </p>
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border text-muted-foreground">
              <th className="px-3 py-1.5 text-left">Time</th>
              <th className="px-3 py-1.5 text-left">Bracket</th>
              <th className="px-3 py-1.5 text-left">Side</th>
              <th className="px-3 py-1.5 text-right">Shares</th>
              <th className="px-3 py-1.5 text-right">Price</th>
              <th className="px-3 py-1.5 text-right">Cost</th>
              <th className="px-3 py-1.5 text-right">Edge</th>
              <th className="px-3 py-1.5 text-right">Kelly</th>
              <th className="px-3 py-1.5 text-left">Why</th>
            </tr>
          </thead>
          <tbody>
            {(data?.trades?.data || []).map((t: any, i: number) => {
              const ctx = t.signal_context || {}
              return (
                <tr key={i} className="border-b border-border/30 hover:bg-accent/30">
                  <td className="px-3 py-1 text-muted-foreground">{t.executed_at?.slice(0, 16)}</td>
                  <td className="px-3 py-1 font-medium">{t.bracket}</td>
                  <td className="px-3 py-1">
                    <span className="rounded bg-success/20 px-1 py-0.5 text-[9px] text-success">{t.side}</span>
                  </td>
                  <td className="px-3 py-1 text-right font-mono">{fmt(t.size)}</td>
                  <td className="px-3 py-1 text-right font-mono">{fmt(t.price * 100)}c</td>
                  <td className="px-3 py-1 text-right font-mono">{formatCurrency(t.size * t.price)}</td>
                  <td className="px-3 py-1 text-right font-mono">{t.signal_edge != null ? `${fmt(t.signal_edge * 100)}%` : "-"}</td>
                  <td className="px-3 py-1 text-right font-mono">{t.signal_kelly_pct != null ? `${fmt(t.signal_kelly_pct * 100)}%` : "-"}</td>
                  <td className="px-3 py-1 text-[10px] text-muted-foreground max-w-[180px] truncate">
                    {ctx.regime && `${ctx.regime} `}
                    {ctx.running_total != null && `total:${ctx.running_total} `}
                    {ctx.momentum && ctx.momentum}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {/* Decision Logs */}
        {(data?.logs || []).length > 0 && (
          <>
            <p className="px-4 py-2 text-xs font-semibold text-muted-foreground uppercase border-b border-t border-border mt-2">
              Decision Log
            </p>
            <div className="space-y-0.5 px-4 py-2">
              {(data?.logs || []).map((l: any, i: number) => (
                <div key={i} className="flex items-start gap-2 text-[10px] py-0.5">
                  <span className="text-muted-foreground shrink-0 w-28">{l.created_at?.slice(0, 16)}</span>
                  <span className={cn(
                    "shrink-0 rounded px-1 py-0.5 text-[8px] font-medium",
                    l.severity === "warning" ? "bg-yellow-500/20 text-yellow-400" :
                    l.severity === "error" ? "bg-destructive/20 text-destructive" :
                    "bg-muted text-muted-foreground"
                  )}>{l.severity}</span>
                  <span className="text-foreground">{l.message}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      <Pagination page={page} total={data?.trades?.total || 0} perPage={30} onPage={setPage} />
    </div>
  )
}

export function AuctionDeepDive({ moduleId }: { moduleId: string }) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<Tab>("Post History")

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-6 py-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground hover:bg-accent/50"
      >
        <span>Auction Deep Dive</span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>
      {open && (
        <div className="border-t border-border">
          <div className="flex border-b border-border">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "px-4 py-2 text-xs font-medium transition-colors",
                  tab === t ? "border-b-2 border-primary text-primary" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {t}
              </button>
            ))}
          </div>
          {tab === "Post History" && <PostHistoryTab moduleId={moduleId} />}
          {tab === "Price History" && <PriceHistoryTab moduleId={moduleId} />}
          {tab === "News & Signals" && <SignalsTab moduleId={moduleId} />}
          {tab === "Bot Decisions" && <DecisionsTab moduleId={moduleId} />}
        </div>
      )}
    </div>
  )
}
