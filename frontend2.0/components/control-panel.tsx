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
    <section
      className="flex h-full w-1/2 min-w-0 flex-col gap-3.5 overflow-hidden border-r border-white/[0.07] px-[30px] py-[34px]"
      style={{ background: "linear-gradient(180deg, #0c0c0e, #060607)" }}
    >
      {/* Header */}
      <header className="flex shrink-0 items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex size-[38px] shrink-0 items-center justify-center rounded-[9px] border border-white/[0.14] bg-[linear-gradient(160deg,#1c1c1f,#0d0d0f)]">
            <Radar className="size-[18px] text-foreground" aria-hidden />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold leading-tight tracking-[-0.01em]">
              SentinelWatch
            </h1>
            <p className="mt-0.5 font-mono text-[9.5px] uppercase tracking-[0.22em] text-muted-foreground">
              Operations Console
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 pt-0.5">
          <div className="flex items-center gap-2 rounded-full border border-white/[0.09] bg-white/[0.04] px-3 py-1.5">
            <span className="relative flex size-1.5">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-foreground opacity-60" />
              <span className="relative inline-flex size-1.5 rounded-full bg-foreground" />
            </span>
            <span className="font-mono text-[9.5px] tracking-[0.06em] text-foreground">
              {loading ? "SINCRONIZANDO" : "PIPELINE · ACTIVO"}
            </span>
          </div>
          {lastSync && (
            <span className="font-mono text-[9.5px] tracking-[0.04em] text-muted-foreground">
              SYNC{" "}
              {lastSync.toLocaleTimeString("es", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </span>
          )}
        </div>
      </header>

      {/* Divider */}
      <div className="h-px shrink-0 bg-white/[0.07]" />

      {/* Error banner */}
      {error && (
        <div className="flex shrink-0 items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/[0.08] px-3 py-2 text-[11px] text-destructive">
          <AlertCircle className="size-3.5 shrink-0" aria-hidden />
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="shrink-0 space-y-3">
        <div>
          <p className="mb-1.5 pl-0.5 font-mono text-[9.5px] uppercase tracking-[0.22em] text-muted-foreground">
            Actividad ilegal
          </p>
          <ActivityTabs value={activity} onChange={onActivityChange} />
        </div>
        <div>
          <p className="mb-1.5 pl-0.5 font-mono text-[9.5px] uppercase tracking-[0.22em] text-muted-foreground">
            Región activa
          </p>
          <RegionSelect value={region} onChange={onRegionChange} />
        </div>
        <div>
          <p className="mb-1.5 pl-0.5 font-mono text-[9.5px] uppercase tracking-[0.22em] text-muted-foreground">
            Veredicto legal
          </p>
          <div
            role="group"
            aria-label="Filtrar por veredicto legal"
            className="grid grid-cols-3 gap-1 rounded-[10px] border border-white/[0.07] bg-white/[0.02] p-1"
          >
            {VERDICT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => onVerdictChange(opt.value)}
                className={cn(
                  "rounded-[7px] px-2 py-2 font-mono text-[10px] tracking-[0.04em] font-medium transition-all",
                  filterVerdict === opt.value
                    ? "border border-white/[0.12] bg-[linear-gradient(180deg,rgba(255,255,255,0.09),rgba(255,255,255,0.04))] text-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
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
        <div className="mb-1.5 flex items-center justify-between pl-0.5">
          <p className="font-mono text-[9.5px] uppercase tracking-[0.22em] text-muted-foreground">
            Índice de alertas
          </p>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-muted-foreground">
              {alerts.length} registros
            </span>
            <button
              onClick={onExportCSV}
              aria-label="Exportar alertas como CSV"
              title="Exportar CSV"
              className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-white/[0.06] hover:text-foreground"
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
