"use client"

/**
 * Next-Auction Countdown card.
 *
 * Shows the next FUTURE auction's start time + a live ticking countdown.
 * If the module has an ACTIVE auction, it shows that one's remaining time
 * instead (the user wants to know "when does the bot trade again?" either
 * way).
 *
 * Data source: /api/modules/{id}/auctions (already returns status + ISO).
 * Refresh: API every 60s, local tick every 1s.
 *
 * Renders nothing if no future or active auction exists (silent on quiet
 * weekends / handles without xTracker coverage).
 */
import { useEffect, useMemo, useState } from "react"
import { useApi } from "@/lib/hooks"
import { Clock } from "lucide-react"
import { cn } from "@/lib/utils"

interface Auction {
  tracking_id: string
  title: string
  start_iso: string
  end_iso: string
  status: "active" | "past" | "future"
  elapsed_days: number
  remaining_days: number
}

function formatLocal(iso: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  return d.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  })
}

function formatDuration(seconds: number): { primary: string; sub: string } {
  if (seconds <= 0) return { primary: "Now", sub: "" }
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  if (days >= 1) {
    return { primary: `${days}d ${hours}h ${minutes}m`, sub: `${secs}s` }
  }
  if (hours >= 1) {
    return { primary: `${hours}h ${minutes}m ${secs}s`, sub: "" }
  }
  return { primary: `${minutes}m ${secs}s`, sub: "" }
}

export function NextAuctionCountdown({ moduleId }: { moduleId: string }) {
  const { data: auctions } = useApi<Auction[]>(`/api/modules/${moduleId}/auctions?include_past=false`, [moduleId], 60_000)

  // Local 1s tick so the countdown ticks without re-fetching the API.
  const [now, setNow] = useState<number>(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  // Pick the most relevant auction: the active one if any, else the soonest
  // future one. Past auctions are excluded by the API param above.
  const target = useMemo(() => {
    if (!auctions || auctions.length === 0) return null
    const active = auctions.find((a) => a.status === "active")
    if (active) return { auction: active, mode: "active" as const }
    const upcoming = auctions
      .filter((a) => a.status === "future" && a.start_iso)
      .sort((a, b) => new Date(a.start_iso).getTime() - new Date(b.start_iso).getTime())
    if (upcoming.length === 0) return null
    return { auction: upcoming[0], mode: "future" as const }
  }, [auctions])

  if (!target) return null

  const { auction, mode } = target
  const targetTime = mode === "active"
    ? new Date(auction.end_iso).getTime()
    : new Date(auction.start_iso).getTime()
  const secondsLeft = Math.max(0, Math.floor((targetTime - now) / 1000))
  const { primary, sub } = formatDuration(secondsLeft)

  // Visual urgency: red within 1h, amber within 6h, otherwise muted.
  const urgency =
    secondsLeft < 60 * 60 ? "destructive" : secondsLeft < 6 * 60 * 60 ? "amber" : "muted"

  const tone =
    urgency === "destructive"
      ? "bg-destructive/10 border-destructive/40 text-destructive"
      : urgency === "amber"
      ? "bg-amber-500/10 border-amber-500/40 text-amber-500"
      : "bg-card border-border text-foreground"

  return (
    <div className={cn("rounded-lg border px-4 py-3", tone)}>
      <div className="flex items-center gap-3">
        <Clock className="h-5 w-5 shrink-0 opacity-80" />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-xs font-semibold uppercase tracking-wider opacity-80">
              {mode === "active" ? "Current auction closes in" : "Next auction opens in"}
            </span>
            <span className="text-lg font-bold tabular-nums">{primary}</span>
            {sub && <span className="text-xs opacity-60 tabular-nums">{sub}</span>}
          </div>
          <div className="mt-0.5 text-xs opacity-75 truncate">
            <span className="font-medium">{auction.title || "—"}</span>
            <span className="mx-1.5 opacity-50">·</span>
            <span>{mode === "active" ? "ends" : "starts"} {formatLocal(mode === "active" ? auction.end_iso : auction.start_iso)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
