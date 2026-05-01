"use client"

import { useApi } from "@/lib/hooks"
import { cn } from "@/lib/utils"
import { CheckCircle2, Eye, Pause, Skull } from "lucide-react"

interface Health {
  state: "trading" | "watching" | "paused" | "killed"
  reason: string
  details?: Record<string, any>
}

const STYLES: Record<Health["state"], { bg: string; border: string; text: string; iconClass: string; Icon: any; label: string }> = {
  trading:  { bg: "bg-success/10",      border: "border-success/40",      text: "text-success",       iconClass: "text-success",       Icon: CheckCircle2, label: "Trading actively" },
  watching: { bg: "bg-amber-500/10",    border: "border-amber-500/40",    text: "text-amber-500",     iconClass: "text-amber-500",     Icon: Eye,          label: "Watching" },
  paused:   { bg: "bg-destructive/10",  border: "border-destructive/40",  text: "text-destructive",   iconClass: "text-destructive",   Icon: Pause,        label: "Paused" },
  killed:   { bg: "bg-muted",           border: "border-muted-foreground", text: "text-muted-foreground", iconClass: "text-muted-foreground", Icon: Skull,    label: "Killed" },
}

export function BotHealthBanner() {
  const { data: health } = useApi<Health>("/api/engine/health", [], 15000)
  if (!health) return null

  const style = STYLES[health.state] || STYLES.paused
  const { Icon, bg, border, text, iconClass, label } = style

  // Stringify details into a single readable line.
  const detailsLine = health.details
    ? Object.entries(health.details)
        .filter(([, v]) => v != null && v !== "")
        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
        .join(" · ")
    : ""

  return (
    <div className={cn(
      "flex items-center gap-3 rounded-lg border px-4 py-2.5",
      bg, border,
    )}>
      <Icon className={cn("h-5 w-5 shrink-0", iconClass)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-sm">
          <span className={cn("font-semibold uppercase tracking-wide text-xs", text)}>
            {label}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-foreground">{health.reason}</span>
        </div>
        {detailsLine && (
          <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
            {detailsLine}
          </div>
        )}
      </div>
    </div>
  )
}
