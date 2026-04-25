"use client"

import { useEffect, useState, ReactNode } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"

const STORAGE_PREFIX = "module-card-collapsed:"

export function CollapsibleCard({
  id,
  title,
  defaultOpen = true,
  children,
}: {
  id: string
  title: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_PREFIX + id)
      if (stored !== null) setOpen(stored === "0" ? false : true)
    } catch {}
    setHydrated(true)
  }, [id])

  useEffect(() => {
    if (!hydrated) return
    try {
      localStorage.setItem(STORAGE_PREFIX + id, open ? "1" : "0")
    } catch {}
  }, [id, open, hydrated])

  if (open) {
    return (
      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="absolute right-3 top-3 z-10 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          aria-label={`Collapse ${title}`}
          title="Collapse"
        >
          <ChevronUp className="h-4 w-4" />
        </button>
        {children}
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={() => setOpen(true)}
      className="flex w-full items-center justify-between rounded-lg border border-border bg-card px-6 py-3 text-left hover:bg-accent/30 transition-colors"
      aria-expanded={false}
    >
      <span className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</span>
      <ChevronDown className="h-4 w-4 text-muted-foreground" />
    </button>
  )
}
