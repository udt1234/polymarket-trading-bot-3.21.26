"use client"

import { useState } from "react"
import { useApi, useMutation } from "@/lib/hooks"
import { ModuleCard } from "@/components/modules/module-card"

export default function ModulesPage() {
  const { data: modules, refetch } = useApi<any[]>("/api/modules/")
  const { mutate: createModule, loading: creating } = useMutation<any>("/api/modules/", "POST")

  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: "",
    market_slug: "",
    strategy: "ensemble",
    budget: 100,
    max_position_pct: 15,
  })

  const handleCreate = async () => {
    await createModule({
      ...form,
      budget: Number(form.budget),
      max_position_pct: Number(form.max_position_pct) / 100,
    })
    setForm({ name: "", market_slug: "", strategy: "ensemble", budget: 100, max_position_pct: 15 })
    setShowForm(false)
    refetch()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Modules</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          {showForm ? "Cancel" : "+ Add Module"}
        </button>
      </div>

      {showForm && (
        <div className="rounded-lg border border-border bg-card p-6 space-y-4">
          <h2 className="text-lg font-semibold">New Module</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Name</label>
              <input
                placeholder="e.g. Election Winner"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Market Slug</label>
              <input
                placeholder="e.g. will-trump-win-2024"
                value={form.market_slug}
                onChange={(e) => setForm({ ...form, market_slug: e.target.value })}
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm font-mono focus:border-primary focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Strategy</label>
              <select
                value={form.strategy}
                onChange={(e) => setForm({ ...form, strategy: e.target.value })}
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
              >
                <option value="ensemble">Ensemble</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Budget ($)</label>
              <input
                type="number"
                value={form.budget}
                onChange={(e) => setForm({ ...form, budget: Number(e.target.value) })}
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Max Position (%)</label>
              <input
                type="number"
                value={form.max_position_pct}
                onChange={(e) => setForm({ ...form, max_position_pct: Number(e.target.value) })}
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <button
              onClick={handleCreate}
              disabled={!form.name || !form.market_slug || creating}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create Module"}
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {modules?.map((m: any) => (
          <ModuleCard
            key={m.id}
            name={m.name}
            strategy={m.strategy}
            status={m.status}
            pnl={0}
            positions={0}
          />
        ))}
      </div>

      {(!modules || modules.length === 0) && (
        <div className="rounded-lg border border-border bg-card p-6 text-center text-muted-foreground">
          <p>No modules configured yet.</p>
        </div>
      )}
    </div>
  )
}
