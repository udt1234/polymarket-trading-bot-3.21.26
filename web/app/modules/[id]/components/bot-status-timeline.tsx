"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"
import { cn } from "@/lib/utils"

interface DecisionLog {
  created_at?: string
  log_type?: string
  message?: string
}

interface Signal {
  bracket?: string
  approved?: boolean
  edge?: number
  rejection_reason?: string
  created_at?: string
}

interface OpenPosition {
  bracket: string
  size: number
  avg_price: number
}

export function BotStatusTimeline({
  decisionLog,
  openPositions,
  signals,
  regimeLabel,
  projectedWinner,
  ensembleAvg,
  marketPrices,
}: {
  decisionLog: DecisionLog[]
  openPositions: OpenPosition[]
  signals: Signal[]
  regimeLabel?: string
  projectedWinner?: string
  ensembleAvg?: number
  marketPrices?: Record<string, number>
}) {
  const [logOpen, setLogOpen] = useState(false)

  const lastEval = decisionLog[0]?.created_at
  const lastEvalRel = lastEval ? relativeTime(new Date(lastEval)) : "never"

  const recentSignals = signals.slice(0, 50)
  const approvedCount = recentSignals.filter((s) => s.approved).length
  const rejectedCount = recentSignals.filter((s) => !s.approved).length
  const topRejection = recentSignals
    .filter((s) => !s.approved && s.rejection_reason)
    .reduce<Record<string, number>>((acc, s) => {
      const key = bucketRejection(s.rejection_reason || "")
      acc[key] = (acc[key] || 0) + 1
      return acc
    }, {})
  const topRejectionEntry = Object.entries(topRejection).sort((a, b) => b[1] - a[1])[0]
  const bestEdgeSignal = recentSignals.reduce<Signal | null>(
    (best, s) => (!best || (s.edge || 0) > (best.edge || 0) ? s : best),
    null,
  )

  // ---- Section A: Right now ---------------------------------------------------
  let nowState: "holding" | "watching-transition" | "watching-spread" | "watching-no-edge" | "starting"
  if (openPositions.length > 0) {
    nowState = "holding"
  } else if (regimeLabel === "TRANSITION") {
    nowState = "watching-transition"
  } else if (topRejectionEntry?.[0] === "spread") {
    nowState = "watching-spread"
  } else if (recentSignals.length === 0) {
    nowState = "starting"
  } else {
    nowState = "watching-no-edge"
  }

  const nowIcon =
    nowState === "holding" ? "🎯" :
    nowState === "watching-transition" ? "⏸" :
    nowState === "watching-spread" ? "🚧" :
    nowState === "starting" ? "⏳" : "👀"

  const nowHeadline =
    nowState === "holding"
      ? `Holding ${openPositions.length} bracket${openPositions.length === 1 ? "" : "s"}`
      : nowState === "watching-transition"
      ? "Watching — regime in transition"
      : nowState === "watching-spread"
      ? "Watching — markets too illiquid"
      : nowState === "starting"
      ? "Just starting — collecting data"
      : "Watching — no edge worth trading"

  const nowSub =
    nowState === "holding"
      ? "Positions held until auction ends. Bot will not trade out unless risk triggers."
      : nowState === "watching-transition"
      ? `Regime is TRANSITION — bot won't trade until trend clears. Last eval ${lastEvalRel}.`
      : nowState === "watching-spread"
      ? `Bid-ask spreads too wide on the brackets with edge. Bot won't buy at bad prices. Last eval ${lastEvalRel}.`
      : nowState === "starting"
      ? "Auction just opened. Models need a few hours of data before signaling."
      : `Models see no bracket with enough edge to bet. Last eval ${lastEvalRel}.`

  // ---- Section B: Why ---------------------------------------------------------
  const cyclesEvaluated = decisionLog.filter((l) => (l.message || "").startsWith("Cycle:")).length
  const tradesPlaced = decisionLog.filter((l) => l.log_type === "execution").length
  const bestEdge = bestEdgeSignal?.edge ? `+${(bestEdgeSignal.edge * 100).toFixed(1)}%` : "—"
  const bestEdgeBracket = bestEdgeSignal?.bracket || ""
  const topRejReason = topRejectionEntry ? humanizeRejection(topRejectionEntry[0]) : null
  const topRejCount = topRejectionEntry?.[1] || 0

  // ---- Section C: Holdings (if holding) --------------------------------------
  const holdingsLines = openPositions.map((p) => {
    const cost = p.size * p.avg_price
    const mkt = marketPrices?.[p.bracket]
    const mktValue = mkt != null ? p.size * mkt : null
    const pnl = mktValue != null ? mktValue - cost : null
    return { bracket: p.bracket, cost, pnl }
  })

  return (
    <div className="mt-3 pt-3 border-t border-border space-y-3">
      {/* A. Right now */}
      <div>
        <p className="text-[10px] font-semibold uppercase text-muted-foreground mb-1.5">Right now</p>
        <div className="flex items-start gap-2">
          <span className="text-lg leading-none mt-0.5">{nowIcon}</span>
          <div className="flex-1">
            <p className="text-sm font-semibold text-foreground">{nowHeadline}</p>
            <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{nowSub}</p>
          </div>
        </div>

        {/* Holdings list shown only when holding */}
        {nowState === "holding" && holdingsLines.length > 0 && (
          <div className="mt-2 ml-7 space-y-1">
            {holdingsLines.map((h, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="font-medium text-foreground">{h.bracket}</span>
                <div className="flex items-center gap-3 text-muted-foreground">
                  <span>${h.cost.toFixed(2)} cost</span>
                  {h.pnl != null && (
                    <span className={cn("font-medium", h.pnl >= 0 ? "text-success" : "text-destructive")}>
                      {h.pnl >= 0 ? "+" : ""}${h.pnl.toFixed(2)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* B. Why */}
      <div className="pt-2 border-t border-border/50">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground mb-1.5">Why</p>
        <ul className="space-y-1 text-xs text-muted-foreground leading-relaxed">
          <li>
            <span className="font-medium text-foreground">{cyclesEvaluated}</span> evaluation
            {cyclesEvaluated === 1 ? "" : "s"} in recent history.{" "}
            <span className="font-medium text-foreground">{tradesPlaced}</span> trade
            {tradesPlaced === 1 ? "" : "s"} placed.
          </li>
          {recentSignals.length > 0 && (
            <li>
              <span className="font-medium text-foreground">
                {approvedCount}/{recentSignals.length}
              </span>{" "}
              signals approved by risk checks.
            </li>
          )}
          {bestEdgeSignal && (
            <li>
              Best edge seen:{" "}
              <span className="font-medium text-success">{bestEdge}</span>
              {bestEdgeBracket && <> on bracket <span className="font-medium text-foreground">{bestEdgeBracket}</span></>}
            </li>
          )}
          {topRejReason && (
            <li>
              Most common skip reason: <span className="font-medium text-foreground">{topRejReason}</span>{" "}
              ({topRejCount}/{rejectedCount} rejections)
            </li>
          )}
          {projectedWinner && (
            <li>
              Models project the winner is <span className="font-medium text-primary">{projectedWinner}</span>
              {ensembleAvg != null && <> at <span className="font-medium text-foreground">~{ensembleAvg.toFixed(0)}</span> posts</>}.
            </li>
          )}
        </ul>
      </div>

      {/* C. Recent activity log (collapsed by default) */}
      {decisionLog.length > 0 && (
        <div className="pt-2 border-t border-border/50">
          <button
            type="button"
            onClick={() => setLogOpen((v) => !v)}
            className="flex w-full items-center justify-between text-[10px] font-semibold uppercase text-muted-foreground hover:text-foreground transition-colors"
          >
            <span>Recent activity ({decisionLog.length})</span>
            {logOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          {logOpen && (
            <div className="mt-2 max-h-[180px] overflow-y-auto space-y-1">
              {decisionLog.slice(0, 30).map((log, i) => {
                const time = log.created_at
                  ? new Date(log.created_at).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : ""
                const isExec = log.log_type === "execution"
                const isRisk = log.log_type === "risk"
                const icon = isExec ? "✅" : isRisk ? "🛡️" : "🔍"
                let msg = log.message || ""
                if (msg.startsWith("Cycle:")) {
                  const sigMatch = msg.match(/signals=(\d+)/)
                  const regMatch = msg.match(/regime=(\w+)/)
                  msg = `Scanned market — ${sigMatch?.[1] || 0} signals, regime ${regMatch?.[1] || "?"}`
                } else if (msg.startsWith("Rejected")) {
                  msg = msg.replace(/^Rejected /, "Skipped ")
                } else if (msg.startsWith("Executed")) {
                  msg = msg.replace(/^Executed /, "Bought ")
                }
                return (
                  <div key={i} className="flex items-start gap-1.5 text-[11px]">
                    <span className="shrink-0 text-muted-foreground w-24">{time}</span>
                    <span>{icon}</span>
                    <span className="text-muted-foreground">{msg}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function bucketRejection(reason: string): string {
  const r = reason.toLowerCase()
  if (r.includes("spread")) return "spread"
  if (r.includes("exposure") || r.includes("cap")) return "exposure"
  if (r.includes("edge")) return "no-edge"
  if (r.includes("kelly")) return "kelly"
  if (r.includes("bankroll")) return "bankroll"
  if (r.includes("regime")) return "regime"
  return "other"
}

function humanizeRejection(key: string): string {
  switch (key) {
    case "spread": return "spread too wide (illiquid market)"
    case "exposure": return "exposure cap reached"
    case "no-edge": return "edge too small after costs"
    case "kelly": return "Kelly sizing rejected (low confidence)"
    case "bankroll": return "bankroll limit"
    case "regime": return "regime not safe"
    default: return "various risk checks"
  }
}

function relativeTime(then: Date): string {
  const diff = (Date.now() - then.getTime()) / 1000
  if (diff < 60) return "just now"
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`
  return `${Math.floor(diff / 86400)} d ago`
}
