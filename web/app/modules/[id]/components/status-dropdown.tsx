"use client"

import { useState, useRef, useEffect } from "react"
import { ChevronDown, Pause, FileText, DollarSign } from "lucide-react"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/api"

interface StatusDropdownProps {
  moduleId: string
  currentStatus: string  // 'active' | 'paper' | 'inactive'
  displayBadge?: string
  onChange?: () => void
}

const OPTIONS = [
  {
    target: "active",
    label: "Real $Trades",
    icon: DollarSign,
    color: "text-success",
    desc: "Trade with real money",
    confirm: true,
  },
  {
    target: "paper",
    label: "Paper Trades",
    icon: FileText,
    color: "text-muted-foreground",
    desc: "Simulated fills, no real money",
    confirm: false,
  },
  {
    target: "inactive",
    label: "Pause",
    icon: Pause,
    color: "text-destructive",
    desc: "Stop new entries (positions still exit)",
    confirm: true,
  },
] as const

const CURRENT_LABEL: Record<string, string> = {
  active: "Real $Trades",
  paper: "Paper Trades",
  inactive: "Paused",
}

export function StatusDropdown({ moduleId, currentStatus, onChange }: StatusDropdownProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  const setStatus = async (target: string, requireConfirm: boolean) => {
    if (target === currentStatus) {
      setOpen(false)
      return
    }
    if (requireConfirm) {
      const labels: Record<string, string> = {
        active: "Switch to Real $Trades? Module will start using real money.",
        inactive: "Pause this module? New entries will stop. Existing positions will keep exiting normally.",
      }
      if (!confirm(labels[target] || `Switch to ${target}?`)) {
        setOpen(false)
        return
      }
    }
    setBusy(true)
    try {
      await apiFetch(`/api/modules/${moduleId}/set-status`, {
        method: "POST",
        body: JSON.stringify({ target }),
      })
      setOpen(false)
      onChange?.()
    } catch (e) {
      alert(`Failed to change status: ${e}`)
    } finally {
      setBusy(false)
    }
  }

  const currentLabel = CURRENT_LABEL[currentStatus] || "Unknown"

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        disabled={busy}
        className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs hover:bg-accent disabled:opacity-50"
      >
        {currentLabel}
        <ChevronDown className="h-3 w-3" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 w-56 rounded-md border border-border bg-popover shadow-lg">
          {OPTIONS.map((opt, i) => {
            const Icon = opt.icon
            const active = opt.target === currentStatus
            return (
              <button
                key={opt.target}
                onClick={() => setStatus(opt.target, opt.confirm)}
                className={cn(
                  "flex w-full items-start gap-2 px-3 py-2 text-left text-xs hover:bg-accent",
                  i === 0 && "rounded-t-md",
                  i === OPTIONS.length - 1 && "rounded-b-md",
                  active && "bg-accent/50",
                )}
              >
                <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", opt.color)} />
                <div className="flex-1">
                  <div className={cn("font-medium", opt.color)}>{opt.label}</div>
                  <div className="text-[10px] text-muted-foreground">{opt.desc}</div>
                </div>
                {active && <span className="text-[10px] text-muted-foreground">current</span>}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
