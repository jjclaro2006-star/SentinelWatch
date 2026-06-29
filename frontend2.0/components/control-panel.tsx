"use client"

import { memo } from "react"
import { ActivityTabs } from "@/components/activity-tabs"
import { RegionSelect, type RegionFilter } from "@/components/region-select"
import { KpiCards } from "@/components/kpi-cards"
import { AlertsTable } from "@/components/alerts-table"
import {
  type ActivityType,
  type Alert,
  type Verdict,
} from "@/lib/sentinel-data"
import { cn } from "@/lib/utils"
import { Radar, Download, AlertCircle } from "lucide-react"

type ActivityFilter = ActivityType | "all"
type VerdictFilter = Verdict | "all"

const VERDICT_OPTIONS: { value: VerdictFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "ILEGAL", label: "ILEGAL" },
  { value: "VERIFICAR", label: "Verificar" },
]

export const ControlPanel = memo(function ControlPanel({
  activity,
  region,
  filterVerdict,
  alerts,
  total,
  avgConfidence,
  wdpaCount,
  selectedId,
  hiddenIds,
  error,
  loading,
  lastSync,
  onActivityChange,
  onRegionChange,
  onVerdictChange,
  onSelect,
  onToggleVisibility,
  onExportCSV,
}: {
  activity: ActivityFilter
  region: RegionFilter
  filterVerdict: VerdictFilter
  alerts: Alert[]
  total: number
  avgConfidence: number
  wdpaCount: number
  selectedId: string | null
  hiddenIds: Set<string>
  error: string | null
  loading: boolean
  lastSync: Date | null
  onActivityChange: (value: ActivityFilter) => void
  onRegionChange: (value: RegionFilter) => void
  onVerdictChange: (value: VerdictFilter) => void
  onSelect: (alert: Alert) => void
  onToggleVisibility: (id: string) => void
  onExportCSV: () => void
}) {
  return (
    <section className="flex h-full w-1/2 min-w-0 flex-col gap-4 overflow-hidden border-r border-border bg-sidebar p-5">
      {/* Header */}
      <header className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-lg bg-primary/15 text-primary ring-1 ring-primary/30">
            <Radar className="size-5" aria-hidden />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">
              SentinelWatch
            </h1>
            <p className="text-xs text-muted-foreground">
              Inteligencia Criminal Ambiental
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1.5">
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-primary" />
            </span>
            <span className="text-[11px] font-medium text-primary">
              {loading ? "Sincronizando…" : "Pipeline: Activo · 8 workers"}
            </span>
          </div>
          {lastSync && (
            <span className="text-[10px] text-muted-foreground">
              Sync {lastSync.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
        </div>
      </header>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-[11px] text-destructive">
          <AlertCircle className="size-3.5 shrink-0" aria-hidden />
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="space-y-3">
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Tipo de actividad ilegal
          </p>
          <ActivityTabs value={activity} onChange={onActivityChange} />
        </div>
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Región de monitoreo
          </p>
          <RegionSelect value={region} onChange={onRegionChange} />
        </div>
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Veredicto legal
          </p>
          <div
            role="group"
            aria-label="Filtrar por veredicto legal"
            className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-secondary/40 p-1"
          >
            {VERDICT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => onVerdictChange(opt.value)}
                className={cn(
                  "rounded-md px-2 py-2 text-[11px] font-medium transition-colors",
                  filterVerdict === opt.value
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* KPIs */}
      <KpiCards
        total={total}
        avgConfidence={avgConfidence}
        wdpaCount={wdpaCount}
        alerts={alerts}
        activity={activity}
      />

      {/* Table */}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Índice de alertas
          </p>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-muted-foreground">
              {alerts.length} registros
            </span>
            <button
              onClick={onExportCSV}
              aria-label="Exportar alertas como CSV"
              title="Exportar CSV"
              className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <Download className="size-3.5" aria-hidden />
            </button>
          </div>
        </div>
        <AlertsTable
          alerts={alerts}
          selectedId={selectedId}
          hiddenIds={hiddenIds}
          loading={loading}
          onSelect={onSelect}
          onToggleVisibility={onToggleVisibility}
        />
      </div>
    </section>
  )
})
