"use client"

import { memo } from "react"
import { ActivityTabs } from "@/components/activity-tabs"
import { RegionSelect, type RegionFilter } from "@/components/region-select"
import { KpiCards } from "@/components/kpi-cards"
import { AlertsTable } from "@/components/alerts-table"
import { type ActivityType, type Alert, type Severity } from "@/lib/sentinel-data"
import { cn } from "@/lib/utils"
import { Radar, Download, AlertCircle } from "lucide-react"
import type { TimeFilter, SeverityFilter } from "@/app/page"

type ActivityFilter = ActivityType | "all"

const TIME_OPTS: { value: TimeFilter; label: string }[] = [
  { value: "7d",  label: "7d" },
  { value: "30d", label: "30d" },
  { value: "90d", label: "90d" },
  { value: "all", label: "Todos" },
]

const SEVERITY_OPTS: {
  value: SeverityFilter
  label: string
  dot: string
}[] = [
  { value: "critica", label: "Crítica", dot: "#f85149" },
  { value: "alta",    label: "Alerta",  dot: "#d29922" },
  { value: "media",   label: "Normal",  dot: "#3fb950" },
]

export const ControlPanel = memo(function ControlPanel({
  activity,
  region,
  severityFilter,
  severityCounts,
  searchQuery,
  timeFilter,
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
  onSeverityChange,
  onTimeChange,
  onSelect,
  onToggleVisibility,
  onExportCSV,
}: {
  activity: ActivityFilter
  region: RegionFilter
  severityFilter: SeverityFilter
  severityCounts: { critica: number; alta: number; media: number }
  timeFilter: TimeFilter
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
  onSeverityChange: (value: SeverityFilter) => void
  onTimeChange: (value: TimeFilter) => void
  onSelect: (alert: Alert) => void
  onToggleVisibility: (id: string) => void
  onExportCSV: () => void
}) {
  return (
    <section
      className="flex h-full w-1/2 min-w-0 flex-col gap-3 overflow-y-auto border-r border-white/[0.07] px-7 py-6"
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
      <div className="shrink-0 space-y-2.5">
        <p className="pl-0.5 font-mono text-[9.5px] uppercase tracking-[0.22em] text-muted-foreground">
          Filtros
        </p>

        {/* Time tabs */}
        <div className="grid grid-cols-4 gap-1 rounded-[10px] border border-white/[0.07] bg-white/[0.02] p-1">
          {TIME_OPTS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onTimeChange(opt.value)}
              className={cn(
                "rounded-[7px] py-1.5 font-mono text-[10px] tracking-[0.04em] font-medium transition-all",
                timeFilter === opt.value
                  ? "border border-white/[0.12] bg-[linear-gradient(180deg,rgba(255,255,255,0.09),rgba(255,255,255,0.04))] text-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Activity tabs */}
        <ActivityTabs value={activity} onChange={onActivityChange} />

        {/* Region */}
        <RegionSelect value={region} onChange={onRegionChange} />

        {/* Severity chips */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => onSeverityChange("all")}
            className={cn(
              "rounded-full border px-3 py-1 font-mono text-[10px] tracking-[0.04em] transition-all",
              severityFilter === "all"
                ? "border-white/[0.2] bg-white/[0.08] text-foreground"
                : "border-white/[0.07] text-muted-foreground hover:border-white/[0.12] hover:text-foreground",
            )}
          >
            Todas
          </button>
          {SEVERITY_OPTS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onSeverityChange(opt.value)}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[10px] tracking-[0.04em] transition-all",
                severityFilter === opt.value
                  ? "border-white/[0.2] bg-white/[0.08] text-foreground"
                  : "border-white/[0.07] text-muted-foreground hover:border-white/[0.12] hover:text-foreground",
              )}
            >
              <span
                className="size-1.5 rounded-full shrink-0"
                style={{ backgroundColor: opt.dot }}
              />
              {opt.label}
              <span className="text-muted-foreground">
                {severityCounts[opt.value as Severity]}
              </span>
            </button>
          ))}
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
      <div className="flex flex-col" style={{ height: "320px" }}>
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
