"use client"

import { usePathname } from "next/navigation"
import { ThemeToggle } from "./theme-toggle"
import { LiveModeToggle } from "@/components/shared/live-mode-toggle"
import { Bell } from "lucide-react"

export function Header() {
  const pathname = usePathname()

  if (pathname === "/login") return null

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-card px-4 md:px-6">
      <div className="flex items-center gap-4">
        <span className="text-sm font-medium text-muted-foreground lg:hidden">PolyBot</span>
      </div>
      <div className="flex items-center gap-2">
        <LiveModeToggle />
        <button className="rounded-md p-2 hover:bg-accent" aria-label="Notifications">
          <Bell className="h-4 w-4" />
        </button>
        <ThemeToggle />
      </div>
    </header>
  )
}
