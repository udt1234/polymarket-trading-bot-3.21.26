"use client"

import { useState } from "react"
import { useApi, useDocumentTitle } from "@/lib/hooks"
import { cn, fmtPrice } from "@/lib/utils"
import { Database, FileText, BarChart3, DollarSign } from "lucide-react"

type View = "raw_posts" | "post_counts" | "prices"

const HANDLES = [
  { value: "realDonaldTrump", label: "Trump (Truth Social)" },
  { value: "elonmusk", label: "Elon (X / Twitter)" },
]

const DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

export default function DataExplorerPage() {
  useDocumentTitle("Data Explorer")
  const [handle, setHandle] = useState("realDonaldTrump")
  const [view, setView] = useState<View>("raw_posts")
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")
  const [hour, setHour] = useState<string>("")
  const [dow, setDow] = useState<string>("")
  const [bracket, setBracket] = useState("")
  const [source, setSource] = useState("")
  const [limit, setLimit] = useState(200)

  const { data: coverage } = useApi<any>(`/api/data-explorer/coverage?handle=${handle}`, [handle], 0)
  const { data: brackets } = useApi<string[]>(`/api/data-explorer/brackets?handle=${handle}`, [handle], 0)
  const { data: sources } = useApi<string[]>(`/api/data-explorer/sources?handle=${handle}`, [handle], 0)

  const params = new URLSearchParams()
  params.set("handle", handle)
  if (start) params.set("start", start)
  if (end) params.set("end", end)
  if (hour) params.set("hour", hour)
  if (dow) params.set("dow", dow)
  if (bracket && view === "prices") params.set("bracket", bracket)
  if (source && view === "post_counts") params.set("source", source)
  params.set("limit", String(limit))

  const endpoint =
    view === "raw_posts" ? `/api/data-explorer/posts?${params}`
    : view === "post_counts" ? `/api/data-explorer/post-counts?${params}`
    : `/api/data-explorer/prices?${params}`

  const { data: results, loading } = useApi<any>(endpoint, [endpoint], 0)
  const rows: any[] = view === "raw_posts" ? (results?.data || []) : (results || [])
  const totalCount = view === "raw_posts" ? results?.total : null

  const fmtDate = (s?: string) => s ? new Date(s).toLocaleString([], { month: "short", day: "numeric", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Database className="h-5 w-5 text-primary" />
        <h1 className="text-2xl font-bold">Data Explorer</h1>
      </div>

      {/* Coverage cards */}
      <div className="flex flex-wrap gap-3">
        {coverage?.raw_posts && (
          <CoverageCard title="Raw Posts" count={coverage.raw_posts.count} oldest={coverage.raw_posts.oldest} newest={coverage.raw_posts.newest} icon={FileText} />
        )}
        {coverage?.counts_xtracker && (
          <CoverageCard title="Counts (xTracker)" count={coverage.counts_xtracker.count} oldest={coverage.counts_xtracker.oldest} newest={coverage.counts_xtracker.newest} icon={BarChart3} />
        )}
        {coverage?.counts_truthsocial_direct && (
          <CoverageCard title="Counts (Direct)" count={coverage.counts_truthsocial_direct.count} oldest={coverage.counts_truthsocial_direct.oldest} newest={coverage.counts_truthsocial_direct.newest} icon={BarChart3} />
        )}
        {coverage?.prices && (
          <CoverageCard title={`Prices (${coverage.prices.brackets} brackets)`} count={coverage.prices.count} oldest={coverage.prices.oldest} newest={coverage.prices.newest} icon={DollarSign} />
        )}
        {coverage?.backfill && !coverage.backfill.is_complete && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs">
            <p className="font-semibold text-amber-400">Trump Backfill In Progress</p>
            <p className="text-muted-foreground mt-1">{coverage.backfill.total_posts_stored.toLocaleString()} posts · oldest {coverage.backfill.oldest_fetched_at?.slice(0, 10)}</p>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex flex-wrap gap-3">
          <Select label="Handle" value={handle} onChange={setHandle} options={HANDLES} />
          <div className="flex gap-1">
            {(["raw_posts", "post_counts", "prices"] as View[]).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium",
                  view === v ? "bg-primary text-primary-foreground" : "border border-border hover:bg-accent"
                )}
              >
                {v === "raw_posts" ? "Raw Posts" : v === "post_counts" ? "Post Counts" : "Bracket Prices"}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <DateInput label="Start" value={start} onChange={setStart} />
          <DateInput label="End" value={end} onChange={setEnd} />

          {view === "raw_posts" && (
            <>
              <Select
                label="Day of Week" value={dow} onChange={setDow}
                options={[{ value: "", label: "Any" }, ...DOWS.map((d, i) => ({ value: String(i), label: d }))]}
              />
              <Select
                label="Hour of Day" value={hour} onChange={setHour}
                options={[{ value: "", label: "Any" }, ...Array.from({ length: 24 }, (_, i) => ({ value: String(i), label: `${i}:00` }))]}
              />
            </>
          )}

          {view === "post_counts" && sources && (
            <Select
              label="Source" value={source} onChange={setSource}
              options={[{ value: "", label: "All" }, ...sources.map(s => ({ value: s, label: s }))]}
            />
          )}

          {view === "prices" && brackets && (
            <Select
              label="Bracket" value={bracket} onChange={setBracket}
              options={[{ value: "", label: "All" }, ...brackets.map(b => ({ value: b, label: b }))]}
            />
          )}

          <Select
            label="Limit" value={String(limit)} onChange={(v) => setLimit(parseInt(v))}
            options={[100, 200, 500, 1000, 2000].map(n => ({ value: String(n), label: String(n) }))}
          />
        </div>
      </div>

      {/* Results */}
      <div className="rounded-lg border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-4 py-2 text-sm">
          <span className="font-semibold">
            {loading ? "Loading…" : `${rows.length} rows${totalCount != null ? ` of ${totalCount.toLocaleString()}` : ""}`}
          </span>
          <span className="text-xs text-muted-foreground">{view}</span>
        </div>

        <div className="overflow-auto max-h-[600px]">
          {view === "raw_posts" && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card border-b border-border text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">When</th>
                  <th className="px-3 py-2 text-left">DOW</th>
                  <th className="px-3 py-2 text-left">Hour</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-left">ID</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const d = new Date(r.created_at)
                  return (
                    <tr key={r.id} className="border-b border-border/50">
                      <td className="px-3 py-1.5">{fmtDate(r.created_at)}</td>
                      <td className="px-3 py-1.5">{DOWS[d.getDay() === 0 ? 6 : d.getDay() - 1]}</td>
                      <td className="px-3 py-1.5">{d.getHours()}:00</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{r.is_reblog ? "reblog" : r.is_reply ? "reply" : "post"}</td>
                      <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">{r.id?.slice(0, 12)}…</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}

          {view === "post_counts" && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card border-b border-border text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">Captured At</th>
                  <th className="px-3 py-2 text-left">Source</th>
                  <th className="px-3 py-2 text-right">Count</th>
                  <th className="px-3 py-2 text-left">Latest Post</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-border/50">
                    <td className="px-3 py-1.5">{fmtDate(r.captured_at)}</td>
                    <td className="px-3 py-1.5"><span className="rounded bg-muted px-1.5 py-0.5 text-xs">{r.source}</span></td>
                    <td className="px-3 py-1.5 text-right font-mono">{r.count}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{fmtDate(r.latest_post_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {view === "prices" && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card border-b border-border text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">Hour</th>
                  <th className="px-3 py-2 text-left">Bracket</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Volume</th>
                  <th className="px-3 py-2 text-left">DOW</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-border/50">
                    <td className="px-3 py-1.5">{fmtDate(r.snapshot_hour)}</td>
                    <td className="px-3 py-1.5 font-medium">{r.bracket}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{fmtPrice(r.price)}</td>
                    <td className="px-3 py-1.5 text-right text-muted-foreground">{r.volume?.toFixed(0) || "—"}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{r.dow != null ? DOWS[r.dow] : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {!loading && rows.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">No data for these filters</p>
          )}
        </div>
      </div>
    </div>
  )
}

function CoverageCard({ title, count, oldest, newest, icon: Icon }: { title: string; count: number; oldest?: string; newest?: string; icon: any }) {
  return (
    <div className="flex-1 min-w-[200px] max-w-[260px] rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
        <Icon className="h-3 w-3" />
        {title}
      </div>
      <p className="mt-1 text-xl font-bold">{count.toLocaleString()}</p>
      <p className="text-xs text-muted-foreground mt-0.5">
        {oldest?.slice(0, 10)} → {newest?.slice(0, 10)}
      </p>
    </div>
  )
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-muted-foreground">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

function DateInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-muted-foreground">{label}</label>
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
      />
    </div>
  )
}
