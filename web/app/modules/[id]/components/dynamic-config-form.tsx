"use client"

import { useState, useEffect, useCallback } from "react"
import { ChevronDown, ChevronUp, Save, RotateCcw } from "lucide-react"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/api"

export interface ConfigSchemaField {
  key: string
  label: string
  type: "number" | "boolean" | "string" | "select" | "number_list_2"
  section?: string
  help?: string
  min?: number
  max?: number
  step?: number
  options?: (string | number)[]
  length?: number              // for number_list_2: number of rows
  cols?: number                // for number_list_2: 1 = flat list, 2 = pairs
  labels?: string[]            // column labels for number_list_2
}

interface DynamicConfigFormProps {
  moduleId: string
  schema: ConfigSchemaField[]
  initialValues: Record<string, any>
  onSaved?: () => void
}

const SECTION_ORDER: string[] = ["general", "buy", "sell", "risk", "advanced"]
const SECTION_LABELS: Record<string, string> = {
  general: "Discovery",
  buy: "Buy Ladder",
  sell: "Sell Rules",
  risk: "Risk Limits",
  advanced: "Advanced",
}

export function DynamicConfigForm({ moduleId, schema, initialValues, onSaved }: DynamicConfigFormProps) {
  const [values, setValues] = useState<Record<string, any>>(initialValues)
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(["general", "buy", "sell"]))

  useEffect(() => {
    setValues(initialValues)
    setDirty(new Set())
  }, [initialValues])

  const setField = useCallback((key: string, val: any) => {
    setValues((v) => ({ ...v, [key]: val }))
    setDirty((d) => new Set(d).add(key))
  }, [])

  const reset = useCallback(() => {
    setValues(initialValues)
    setDirty(new Set())
  }, [initialValues])

  const save = useCallback(async () => {
    if (dirty.size === 0) return
    setSaving(true)
    try {
      // Send only the dirty fields so we don't accidentally re-write
      // unchanged values that may have been edited from another tab.
      const payload: Record<string, any> = {}
      dirty.forEach((k) => { payload[k] = values[k] })
      await apiFetch(`/api/modules/${moduleId}/config-dynamic`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
      setDirty(new Set())
      onSaved?.()
    } catch (e) {
      alert(`Failed to save: ${e}`)
    } finally {
      setSaving(false)
    }
  }, [dirty, values, moduleId, onSaved])

  // Group fields by section
  const grouped = schema.reduce<Record<string, ConfigSchemaField[]>>((acc, f) => {
    const s = f.section || "general"
    ;(acc[s] = acc[s] || []).push(f)
    return acc
  }, {})

  const sectionKeys: string[] = SECTION_ORDER.filter((s) => grouped[s]?.length).concat(
    Object.keys(grouped).filter((s) => !SECTION_ORDER.includes(s))
  )

  const toggleSection = (s: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }

  return (
    <div className="space-y-4">
      {sectionKeys.map((sec) => {
        const isOpen = openSections.has(sec)
        return (
          <div key={sec} className="rounded-md border border-border/60">
            <button
              onClick={() => toggleSection(sec)}
              className="flex w-full items-center justify-between px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-accent/30"
            >
              <span>{SECTION_LABELS[sec] || sec}</span>
              {isOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
            {isOpen && (
              <div className="grid grid-cols-1 gap-3 border-t border-border/60 p-4 sm:grid-cols-2 lg:grid-cols-3">
                {grouped[sec].map((f) => (
                  <FieldEditor
                    key={f.key}
                    field={f}
                    value={values[f.key]}
                    dirty={dirty.has(f.key)}
                    onChange={(v) => setField(f.key, v)}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}

      <div className="flex items-center justify-between border-t border-border pt-4">
        <p className="text-xs text-muted-foreground">
          {dirty.size === 0
            ? "No unsaved changes"
            : `${dirty.size} unsaved field${dirty.size === 1 ? "" : "s"}`}
        </p>
        <div className="flex gap-2">
          <button
            onClick={reset}
            disabled={dirty.size === 0 || saving}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </button>
          <button
            onClick={save}
            disabled={dirty.size === 0 || saving}
            className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {saving ? "Saving..." : "Save Config"}
          </button>
        </div>
      </div>
    </div>
  )
}

function FieldEditor({
  field, value, dirty, onChange,
}: {
  field: ConfigSchemaField
  value: any
  dirty: boolean
  onChange: (v: any) => void
}) {
  const inputCls = cn(
    "w-full rounded border bg-background px-2 py-1 text-sm",
    dirty ? "border-yellow-500/60 bg-yellow-500/5" : "border-border",
  )

  if (field.type === "boolean") {
    return (
      <label className="flex items-center gap-2 self-end pb-1.5" title={field.help}>
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded border-border"
        />
        <span className="text-sm">{field.label}</span>
        {dirty && <span className="ml-auto text-[10px] text-yellow-500">●</span>}
      </label>
    )
  }

  if (field.type === "select") {
    return (
      <label className="space-y-1" title={field.help}>
        <span className="flex items-center justify-between text-xs text-muted-foreground">
          {field.label}
          {dirty && <span className="text-yellow-500">●</span>}
        </span>
        <select
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
        >
          {(field.options || []).map((o) => (
            <option key={String(o)} value={String(o)}>{String(o)}</option>
          ))}
        </select>
      </label>
    )
  }

  if (field.type === "number_list_2") {
    const length = field.length ?? 4
    const cols = field.cols ?? 1
    const rows: any[] = Array.isArray(value) ? value : []
    return (
      <div className="col-span-1 sm:col-span-2 lg:col-span-3 space-y-1.5" title={field.help}>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{field.label}</span>
          {dirty && <span className="text-yellow-500">●</span>}
        </div>
        <div className={cn(
          "grid gap-2",
          cols === 2 ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-2 sm:grid-cols-4",
        )}>
          {Array.from({ length }).map((_, i) => {
            if (cols === 2) {
              // Some keys (e.g. buy_ladder) store as list of {price, pct} dicts
              // server-side. Normalize to [a, b] for the editor.
              const raw = rows[i]
              const pair = Array.isArray(raw)
                ? raw
                : (raw && typeof raw === "object" && "price" in (raw as any))
                  ? [(raw as any).price ?? 0, (raw as any).pct ?? 0]
                  : [0, 0]
              const labels = field.labels && field.labels.length === 2 ? field.labels : ["a", "b"]
              return (
                <div key={i} className="rounded border border-border/60 bg-muted/10 p-2">
                  <div className="mb-1 text-[10px] uppercase text-muted-foreground">Row {i + 1}</div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {[0, 1].map((j) => (
                      <label key={j} className="space-y-0.5">
                        <span className="text-[10px] text-muted-foreground">{labels[j]}</span>
                        <input
                          type="number"
                          step="any"
                          value={pair[j] ?? 0}
                          onChange={(e) => {
                            const nextRows = Array.from({ length }).map((_, idx) =>
                              idx === i
                                ? (idx === i ? [j === 0 ? +e.target.value : pair[0], j === 1 ? +e.target.value : pair[1]] : pair)
                                : (Array.isArray(rows[idx]) ? rows[idx] : [0, 0])
                            )
                            onChange(nextRows)
                          }}
                          className={cn(
                            "w-full rounded border bg-background px-1.5 py-1 text-xs",
                            dirty ? "border-yellow-500/60" : "border-border",
                          )}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )
            }
            // flat list
            const cellLabel = field.labels?.[i] ?? `T${i + 1}`
            return (
              <label key={i} className="space-y-0.5">
                <span className="text-[10px] text-muted-foreground">{cellLabel}</span>
                <input
                  type="number"
                  step="any"
                  value={rows[i] ?? 0}
                  onChange={(e) => {
                    const next = Array.from({ length }).map((_, idx) =>
                      idx === i ? +e.target.value : (rows[idx] ?? 0)
                    )
                    onChange(next)
                  }}
                  className={cn(
                    "w-full rounded border bg-background px-2 py-1 text-sm",
                    dirty ? "border-yellow-500/60" : "border-border",
                  )}
                />
              </label>
            )
          })}
        </div>
      </div>
    )
  }

  // number / string
  return (
    <label className="space-y-1" title={field.help}>
      <span className="flex items-center justify-between text-xs text-muted-foreground">
        {field.label}
        {dirty && <span className="text-yellow-500">●</span>}
      </span>
      <input
        type={field.type === "number" ? "number" : "text"}
        value={value ?? ""}
        min={field.min}
        max={field.max}
        step={field.step}
        onChange={(e) => onChange(field.type === "number" ? +e.target.value : e.target.value)}
        className={inputCls}
      />
    </label>
  )
}
