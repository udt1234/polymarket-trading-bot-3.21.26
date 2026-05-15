"use client"

import { useApi } from "@/lib/hooks"
import { cn } from "@/lib/utils"
import { CheckCircle2, Eye, Pause, Skull, ShieldAlert } from "lucide-react"

interface CircuitBreaker {
  consecutive_losses: number
  max_consecutive_losses: number
  tripped: boolean
}

interface Health {
  state: "trading" | "watching" | "degraded" | "paused" | "killed"
  reason: string
  plain_english?: string  // Optional layman-terms explanation rendered under the technical reason.
  details?: Record<string, any>
}

const STYLES: Record<Health["state"], { bg: string; border: string; text: string; iconClass: string; Icon: any; label: string }> = {
  trading:  { bg: "bg-success/10",      border: "border-success/40",      text: "text-success",       iconClass: "text-success",       Icon: CheckCircle2, label: "Trading actively" },
  watching: { bg: "bg-amber-500/10",    border: "border-amber-500/40",    text: "text-amber-500",     iconClass: "text-amber-500",     Icon: Eye,          label: "Watching" },
  degraded: { bg: "bg-amber-500/10",    border: "border-amber-500/40",    text: "text-amber-500",     iconClass: "text-amber-500",     Icon: ShieldAlert,  label: "Degraded" },
  paused:   { bg: "bg-destructive/10",  border: "border-destructive/40",  text: "text-destructive",   iconClass: "text-destructive",   Icon: Pause,        label: "Paused" },
  killed:   { bg: "bg-muted",           border: "border-muted-foreground", text: "text-muted-foreground", iconClass: "text-muted-foreground", Icon: Skull,    label: "Killed" },
}

function CircuitBreakerPill({ cb }: { cb: CircuitBreaker }) {
  const max = Math.max(cb.max_consecutive_losses || 5, 1)
  const cur = Math.max(0, cb.consecutive_losses || 0)
  // Color tier: green when far from cap, amber halfway, red near/past cap.
  const ratio = cur / max
  const tone =
    cb.tripped ? "bg-destructive/15 text-destructive border-destructive/40"
    : ratio >= 0.8 ? "bg-destructive/10 text-destructive border-destructive/30"
    : ratio >= 0.5 ? "bg-amber-500/15 text-amber-500 border-amber-500/30"
    : "bg-muted text-muted-foreground border-border"
  return (
    <span
      title={
        cb.tripped
          ? "Circuit breaker TRIPPED — all modules paused until cooldown clears."
          : `Bot-wide consecutive losses across all modules. Auto-pauses the module that lands the ${max}th loss.`
      }
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tone,
      )}
    >
      <ShieldAlert className="h-3 w-3" />
      Trips: {cur}/{max}{cb.tripped ? " · TRIPPED" : ""}
    </span>
  )
}

export function BotHealthBanner({ moduleId }: { moduleId?: string } = {}) {
  const url = moduleId ? `/api/engine/health?module_id=${moduleId}` : "/api/engine/health"
  const { data: health } = useApi<Health>(url, [moduleId], 15000)
  if (!health) return null

  const style = STYLES[health.state] || STYLES.paused
  const { Icon, bg, border, text, iconClass, label } = style

  // Pull circuit_breaker out of details so it renders as a pill (not as a
  // raw [object Object] string in the catch-all detail line).
  const cb: CircuitBreaker | undefined = health.details?.circuit_breaker
  const otherDetails = health.details
    ? Object.entries(health.details).filter(([k, v]) => k !== "circuit_breaker" && v != null && v !== "")
    : []
  const detailsLine = otherDetails
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
    .join(" · ")

  return (
    <div className={cn(
      "flex items-center gap-3 rounded-lg border px-4 py-2.5",
      bg, border,
    )}>
      <Icon className={cn("h-5 w-5 shrink-0", iconClass)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className={cn("font-semibold uppercase tracking-wide text-xs", text)}>
            {label}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-foreground">{health.reason}</span>
          {cb && <CircuitBreakerPill cb={cb} />}
        </div>
        {health.plain_english && (
          <div className="text-xs text-foreground/80 mt-1">
            {health.plain_english}
          </div>
        )}
        {detailsLine && (
          <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
            {detailsLine}
          </div>
        )}
      </div>
    </div>
  )
}
