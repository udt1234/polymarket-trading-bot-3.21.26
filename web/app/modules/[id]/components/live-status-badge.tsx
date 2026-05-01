"use client"

import { useApi } from "@/lib/hooks"
import { cn } from "@/lib/utils"

interface Health {
  state: "trading" | "watching" | "paused" | "killed"
  reason: string
  details?: Record<string, any>
}

interface LiveStatusBadgeProps {
  // Operator-set module status from the modules table.
  // Takes precedence over engine health for paused/killed values.
  moduleStatus: string
}

const STYLES: Record<string, string> = {
  trading: "bg-success/20 text-success",
  watching: "bg-amber-500/20 text-amber-500",
  paused: "bg-destructive/20 text-destructive",
  paused_manual: "bg-yellow-500/20 text-yellow-500",
  killed: "bg-muted text-muted-foreground",
  enabled: "bg-success/20 text-success",
  paper: "bg-blue-500/20 text-blue-500",
}

const LABELS: Record<string, string> = {
  trading: "Trading",
  watching: "Watching",
  paused: "Paused",
  paused_manual: "Paused (manual)",
  killed: "Killed",
  enabled: "Enabled",
  paper: "Paper",
}

export function LiveStatusBadge({ moduleStatus }: LiveStatusBadgeProps) {
  const { data: health } = useApi<Health>("/api/engine/health", [], 15000)

  // Operator-driven states win over engine state. If the operator paused/killed
  // the module, that's the ground truth — engine.health is irrelevant.
  let key: string
  let title: string
  if (moduleStatus === "killed") {
    key = "killed"
    title = "Module killed by operator. Use Resume to bring it back."
  } else if (moduleStatus === "paused") {
    key = "paused_manual"
    title = "Module paused by operator. Use Resume to allow trading."
  } else if (moduleStatus === "paper") {
    key = "paper"
    title = "Module is in paper mode (simulated trades only)."
  } else if (!health) {
    key = "enabled"
    title = "Module enabled. Awaiting bot health snapshot."
  } else if (health.state === "killed") {
    key = "killed"
    title = `Engine state: killed. ${health.reason}`
  } else if (health.state === "paused") {
    key = "paused"
    title = `Engine paused: ${health.reason}`
  } else if (health.state === "watching") {
    key = "watching"
    title = `Bot is watching but not trading. ${health.reason}`
  } else if (health.state === "trading") {
    key = "trading"
    title = `Bot is actively trading. ${health.reason}`
  } else {
    key = "enabled"
    title = "Module enabled."
  }

  return (
    <span
      title={title}
      className={cn(
        "rounded-full px-2 py-0.5 text-xs font-medium capitalize",
        STYLES[key] || STYLES.enabled,
      )}
    >
      {LABELS[key] || "Enabled"}
    </span>
  )
}
