"use client"

import { useState } from "react"
import { useApi, useMutation } from "@/lib/hooks"
import { cn } from "@/lib/utils"

interface RiskSettings {
  paper_mode: boolean
}

export function LiveModeToggle() {
  const { data, refetch } = useApi<RiskSettings>("/api/settings/risk")
  const { mutate } = useMutation("/api/settings/risk", "PUT")
  const [confirming, setConfirming] = useState(false)

  const isPaper = data?.paper_mode !== false

  const handleToggle = () => {
    if (!isPaper) {
      mutate({ paper_mode: true }).then(() => refetch())
      return
    }
    setConfirming(true)
  }

  const confirmLive = () => {
    mutate({ paper_mode: false }).then(() => {
      setConfirming(false)
      refetch()
    })
  }

  return (
    <>
      <button
        onClick={handleToggle}
        className={cn(
          "relative flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-colors",
          isPaper
            ? "bg-blue-500/20 text-blue-400 hover:bg-blue-500/30"
            : "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
        )}
      >
        <span className={cn("h-2 w-2 rounded-full", isPaper ? "bg-blue-400" : "bg-emerald-400 animate-pulse")} />
        {isPaper ? "PAPER" : "LIVE"}
      </button>

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-foreground">Switch to LIVE mode?</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Real money will be used. Make sure your wallet is funded and risk parameters are set.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirming(false)}
                className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
              >
                Cancel
              </button>
              <button
                onClick={confirmLive}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
              >
                Confirm LIVE
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
