"use client"

/**
 * Global trading-mode indicator.
 *
 * Per-module status (active / paper / inactive) is authoritative — there is
 * no global PAPER override anymore. This badge just summarizes what's going
 * on across all modules:
 *   - "LIVE"  — at least one module has status='active' (trading real money)
 *   - "PAPER" — all modules are paper or inactive (no real-money trading)
 *
 * It is read-only. To change a module's mode, use the per-module status
 * dropdown on its dashboard.
 */
import { useApi } from "@/lib/hooks"
import { cn } from "@/lib/utils"

interface ModuleSummary {
  id: string
  status: string
}

export function LiveModeToggle() {
  const { data: modules } = useApi<ModuleSummary[]>("/api/modules/")
  const anyLive = (modules || []).some((m) => (m?.status || "").toLowerCase() === "active")

  return (
    <div
      title={
        anyLive
          ? "At least one module is trading real money. Open the module to change its status."
          : "No modules are live. Open a module and use its status dropdown to flip it to Real $ Trades."
      }
      className={cn(
        "relative flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold",
        anyLive
          ? "bg-emerald-500/20 text-emerald-400"
          : "bg-blue-500/20 text-blue-400"
      )}
    >
      <span className={cn("h-2 w-2 rounded-full", anyLive ? "bg-emerald-400 animate-pulse" : "bg-blue-400")} />
      {anyLive ? "LIVE" : "PAPER"}
    </div>
  )
}
