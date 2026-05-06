"use client"

import { useState, useEffect, useCallback } from "react"
import { ChevronDown, ChevronUp, Plus, Trash2, Save, RotateCcw } from "lucide-react"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/api"

interface BracketProfile {
  bracket: string
  label: string
  enabled: boolean
  strategy_name: string
  bracket_max_count: number
  params?: Record<string, any>
}

interface AuctionType {
  id: string
  label: string
  enabled: boolean
  handle: string
  platform: string
  series_slug: string
  window_days: number
  bracket_profiles: BracketProfile[]
}

interface StrategyMeta {
  name: string
  label: string
  default_params: Record<string, any>
}

interface AuctionTypesEditorProps {
  moduleId: string
  initialValue: AuctionType[]
  strategies: StrategyMeta[]
  onSaved?: () => void
}

export function AuctionTypesEditor({
  moduleId, initialValue, strategies, onSaved,
}: AuctionTypesEditorProps) {
  const [value, setValue] = useState<AuctionType[]>(initialValue || [])
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [openTypes, setOpenTypes] = useState<Set<string>>(new Set())

  useEffect(() => {
    setValue(initialValue || [])
    setDirty(false)
    // Auto-open enabled auction types on first load
    const enabledIds = (initialValue || []).filter(at => at.enabled).map(at => at.id)
    setOpenTypes(new Set(enabledIds))
  }, [initialValue])

  const update = (next: AuctionType[]) => {
    setValue(next)
    setDirty(true)
  }

  const updateAuctionType = (idx: number, patch: Partial<AuctionType>) => {
    update(value.map((at, i) => i === idx ? { ...at, ...patch } : at))
  }

  const updateProfile = (atIdx: number, pIdx: number, patch: Partial<BracketProfile>) => {
    update(value.map((at, i) => {
      if (i !== atIdx) return at
      return {
        ...at,
        bracket_profiles: at.bracket_profiles.map((p, j) =>
          j === pIdx ? { ...p, ...patch } : p,
        ),
      }
    }))
  }

  const updateProfileParam = (atIdx: number, pIdx: number, key: string, val: any) => {
    update(value.map((at, i) => {
      if (i !== atIdx) return at
      return {
        ...at,
        bracket_profiles: at.bracket_profiles.map((p, j) => {
          if (j !== pIdx) return p
          return { ...p, params: { ...(p.params || {}), [key]: val } }
        }),
      }
    }))
  }

  const addProfile = (atIdx: number) => {
    const at = value[atIdx]
    const newProfile: BracketProfile = {
      bracket: "new",
      label: `${at.id}_new`,
      enabled: false,
      strategy_name: strategies[0]?.name || "Cheap_Lottery_Pacing",
      bracket_max_count: 40,
      params: {},
    }
    update(value.map((a, i) => i === atIdx
      ? { ...a, bracket_profiles: [...a.bracket_profiles, newProfile] }
      : a))
  }

  const removeProfile = (atIdx: number, pIdx: number) => {
    if (!confirm("Remove this bracket profile? This will not delete existing positions.")) return
    update(value.map((a, i) => i === atIdx
      ? { ...a, bracket_profiles: a.bracket_profiles.filter((_, j) => j !== pIdx) }
      : a))
  }

  const reset = () => { setValue(initialValue || []); setDirty(false) }

  const save = async () => {
    setSaving(true)
    try {
      await apiFetch(`/api/modules/${moduleId}/config-dynamic`, {
        method: "PUT",
        body: JSON.stringify({ auction_types: value }),
      })
      setDirty(false)
      onSaved?.()
    } catch (e) {
      alert(`Save failed: ${e}`)
    } finally {
      setSaving(false)
    }
  }

  const toggleType = (id: string) => {
    setOpenTypes(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Configure which auction types and bracket profiles the bot trades. Disabled
          profiles are kept but not evaluated. Per-profile params override the strategy's defaults.
        </p>
      </div>

      {value.map((at, atIdx) => {
        const isOpen = openTypes.has(at.id)
        const enabledCount = at.bracket_profiles.filter(p => p.enabled).length
        return (
          <div key={at.id} className="rounded-md border border-border/60">
            <div className="flex items-center justify-between px-4 py-2 bg-accent/20">
              <button
                onClick={() => toggleType(at.id)}
                className="flex flex-1 items-center gap-2 text-left"
              >
                {isOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                <span className="text-sm font-semibold">{at.label}</span>
                <span className="text-xs text-muted-foreground">
                  {enabledCount}/{at.bracket_profiles.length} profiles enabled
                </span>
              </button>
              <label className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={at.enabled}
                  onChange={(e) => updateAuctionType(atIdx, { enabled: e.target.checked })}
                />
                Enabled
              </label>
            </div>

            {isOpen && (
              <div className="border-t border-border/60 p-3 space-y-3">
                {/* Auction-level fields */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Field label="Handle" value={at.handle} onChange={v => updateAuctionType(atIdx, { handle: v })} />
                  <Field label="Platform" value={at.platform} onChange={v => updateAuctionType(atIdx, { platform: v })} />
                  <Field label="Series Slug" value={at.series_slug} onChange={v => updateAuctionType(atIdx, { series_slug: v })} />
                  <Field label="Window (days)" value={String(at.window_days)} type="number"
                    onChange={v => updateAuctionType(atIdx, { window_days: Number(v) })} />
                </div>

                {/* Profiles */}
                <div className="space-y-2">
                  {at.bracket_profiles.map((p, pIdx) => (
                    <ProfileEditor
                      key={pIdx}
                      profile={p}
                      strategies={strategies}
                      onChange={(patch) => updateProfile(atIdx, pIdx, patch)}
                      onChangeParam={(k, v) => updateProfileParam(atIdx, pIdx, k, v)}
                      onRemove={() => removeProfile(atIdx, pIdx)}
                    />
                  ))}
                  <button
                    onClick={() => addProfile(atIdx)}
                    className="flex items-center gap-1 rounded border border-dashed border-border px-2 py-1 text-xs text-muted-foreground hover:bg-accent"
                  >
                    <Plus className="h-3 w-3" /> Add Bracket Profile
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}

      <div className="flex items-center justify-between border-t border-border pt-3">
        <p className="text-xs text-muted-foreground">
          {dirty ? "Unsaved changes" : "No changes"}
        </p>
        <div className="flex gap-2">
          <button
            onClick={reset}
            disabled={!dirty || saving}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </button>
          <button
            onClick={save}
            disabled={!dirty || saving}
            className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" /> {saving ? "Saving..." : "Save Auction Types"}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, value, onChange, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; type?: string
}) {
  return (
    <label className="space-y-0.5">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
      />
    </label>
  )
}

function ProfileEditor({
  profile, strategies, onChange, onChangeParam, onRemove,
}: {
  profile: BracketProfile
  strategies: StrategyMeta[]
  onChange: (patch: Partial<BracketProfile>) => void
  onChangeParam: (key: string, value: any) => void
  onRemove: () => void
}) {
  const [paramsOpen, setParamsOpen] = useState(false)
  const strategyMeta = strategies.find(s => s.name === profile.strategy_name)
  const effectiveParams = { ...(strategyMeta?.default_params || {}), ...(profile.params || {}) }

  return (
    <div className={cn(
      "rounded border p-2 space-y-2",
      profile.enabled ? "border-success/40 bg-success/5" : "border-border/60 bg-muted/10",
    )}>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-xs">
          <input
            type="checkbox"
            checked={profile.enabled}
            onChange={(e) => onChange({ enabled: e.target.checked })}
          />
          Enabled
        </label>
        <Field label="Bracket" value={profile.bracket} onChange={v => onChange({ bracket: v })} />
        <Field label="Label" value={profile.label} onChange={v => onChange({ label: v })} />
        <Field label="Bracket Max Count" type="number" value={String(profile.bracket_max_count)}
          onChange={v => onChange({ bracket_max_count: Number(v) })} />
        <label className="space-y-0.5">
          <span className="text-[10px] text-muted-foreground">Strategy</span>
          <select
            value={profile.strategy_name}
            onChange={(e) => onChange({ strategy_name: e.target.value })}
            className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
          >
            {strategies.map(s => (
              <option key={s.name} value={s.name}>{s.label}</option>
            ))}
          </select>
        </label>
        <button
          onClick={onRemove}
          className="ml-auto rounded p-1 text-destructive hover:bg-destructive/10"
          title="Remove profile"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <button
        onClick={() => setParamsOpen(!paramsOpen)}
        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
      >
        {paramsOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        Strategy params ({Object.keys(effectiveParams).length})
      </button>
      {paramsOpen && (
        <div className="rounded border border-border/40 bg-background/40 p-2 space-y-1">
          {Object.entries(effectiveParams).map(([k, v]) => (
            <div key={k} className="flex items-start gap-2 text-[11px]">
              <span className="w-40 shrink-0 font-mono text-muted-foreground">{k}</span>
              {typeof v === "boolean" ? (
                <input
                  type="checkbox"
                  checked={!!v}
                  onChange={(e) => onChangeParam(k, e.target.checked)}
                />
              ) : Array.isArray(v) ? (
                <input
                  className="flex-1 rounded border border-border bg-background px-1.5 py-0.5 text-[11px] font-mono"
                  value={JSON.stringify(v)}
                  onChange={(e) => {
                    try { onChangeParam(k, JSON.parse(e.target.value)) } catch { /* ignore until valid */ }
                  }}
                />
              ) : typeof v === "number" ? (
                <input
                  type="number"
                  step="any"
                  value={v}
                  onChange={(e) => onChangeParam(k, Number(e.target.value))}
                  className="flex-1 rounded border border-border bg-background px-1.5 py-0.5 text-[11px]"
                />
              ) : (
                <input
                  value={String(v ?? "")}
                  onChange={(e) => onChangeParam(k, e.target.value)}
                  className="flex-1 rounded border border-border bg-background px-1.5 py-0.5 text-[11px]"
                />
              )}
              <span className={cn("text-[9px]", profile.params && k in profile.params ? "text-yellow-500" : "text-muted-foreground/50")}>
                {profile.params && k in profile.params ? "override" : "default"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
