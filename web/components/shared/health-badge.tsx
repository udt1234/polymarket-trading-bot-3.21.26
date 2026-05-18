import { cn } from "@/lib/utils"

// Runtime health — separate from operator-intent status. Tells Sir whether
// the module is ACTUALLY working, not just whether it's flagged active.
type Badge = "trading" | "cycling" | "stuck" | "unknown"

const BADGE_STYLES: Record<Badge, string> = {
  trading: "bg-success/20 text-success border-success/30",
  cycling: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  stuck: "bg-destructive/20 text-destructive border-destructive/30",
  unknown: "bg-muted text-muted-foreground border-border",
}

const BADGE_LABELS: Record<Badge, string> = {
  trading: "Trading",
  cycling: "Cycling",
  stuck: "Stuck",
  unknown: "Unknown",
}

const BADGE_DOTS: Record<Badge, string> = {
  trading: "bg-success",
  cycling: "bg-amber-400",
  stuck: "bg-destructive",
  unknown: "bg-muted-foreground",
}

interface HealthBadgeProps {
  health?: {
    badge?: string
    reason?: string
    trades_24h?: number
    errors_1h?: number
    last_cycle_at?: string | null
  } | null
  // If true, show the reason inline below the badge. If false (default),
  // reason only shows as a hover title.
  showReason?: boolean
  className?: string
}

export function HealthBadge({ health, showReason = false, className }: HealthBadgeProps) {
  const badge = ((health?.badge as Badge) || "unknown") in BADGE_STYLES
    ? (health?.badge as Badge)
    : "unknown"
  const reason = health?.reason || ""
  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <span
        title={reason}
        className={cn(
          "inline-flex items-center gap-1 self-start rounded-full border px-2 py-0.5 text-xs font-medium",
          BADGE_STYLES[badge],
        )}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", BADGE_DOTS[badge])} aria-hidden />
        {BADGE_LABELS[badge]}
      </span>
      {showReason && reason && (
        <span className="text-xs text-muted-foreground" title={reason}>
          {reason}
        </span>
      )}
    </div>
  )
}
