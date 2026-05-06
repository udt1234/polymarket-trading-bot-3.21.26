"use client"

import { cn } from "@/lib/utils"

interface LiveStatusBadgeProps {
  // display_badge value from the API (real_trading | paper_trading | inactive)
  displayBadge?: string
  // Optional: human-readable inactive reason for tooltip
  inactiveReasonHuman?: string | null
  inactiveDetail?: string | null
}

const BADGE_STYLES: Record<string, string> = {
  real_trading: "bg-success/20 text-success",                      // green
  paper_trading: "bg-muted text-muted-foreground",                 // grey dot
  inactive: "bg-destructive/20 text-destructive",                  // red
}

const BADGE_LABELS: Record<string, string> = {
  real_trading: "Real $Trades",
  paper_trading: "Paper Trades",
  inactive: "Inactive",
}

export function LiveStatusBadge({
  displayBadge = "paper_trading",
  inactiveReasonHuman,
  inactiveDetail,
}: LiveStatusBadgeProps) {
  const key = BADGE_STYLES[displayBadge] ? displayBadge : "paper_trading"

  let title = BADGE_LABELS[key]
  if (key === "inactive") {
    if (inactiveReasonHuman) title = `Inactive — ${inactiveReasonHuman}`
    if (inactiveDetail) title += `\n${inactiveDetail}`
  } else if (key === "real_trading") {
    title = "Real money trading — module is live"
  } else {
    title = "Paper trading — simulated fills, no real money"
  }

  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        BADGE_STYLES[key],
      )}
    >
      {key === "paper_trading" && (
        <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/70" aria-hidden />
      )}
      {BADGE_LABELS[key]}
    </span>
  )
}
