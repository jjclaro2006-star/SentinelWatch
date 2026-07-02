"use client"

import { useCallback, useMemo, useState } from "react"
import dynamic from "next/dynamic"
import { ControlPanel } from "@/components/control-panel"
import { useAlerts } from "@/hooks/useAlerts"
import type { RegionFilter } from "@/components/region-select"

const MapViewport = dynamic(
  () => import("@/components/map-viewport").then((m) => m.MapViewport),
  { ssr: false, loading: () => <div className="flex-1 h-full bg-[#0d1117]" /> },
)
import { exportAlertsCSV } from "@/lib/utils"
import type { ActivityType, Alert, Severity } from "@/lib/sentinel-data"

type ActivityFilter = ActivityType | "all"
type SeverityFilter = Severity | "all"
export type TimeFilter = "7d" | "30d" | "90d" | "all"
export type SeverityFilter = Severity | "all"

export default function Page() {
  const { alerts, summary, error, loading, lastSync } = useAlerts()

  const [activity, setActivity] = useState<ActivityFilter>("mineria")
  const [region, setRegion] = useState<RegionFilter>("peru")
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all")
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("all")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set())

  // Pre-severity filtered set — used for severity chip counts
  const preFiltered = useMemo(() => {
    const cutoff =
      timeFilter !== "all"
        ? new Date(Date.now() - parseInt(timeFilter) * 24 * 60 * 60 * 1000)
            .toISOString()
            .split("T")[0]
        : null

    return alerts.filter(
      (a) =>
        (region === "all" || a.region === region) &&
        (activity === "all" || a.type === activity) &&
        (a.type !== "mineria" || a.confidence >= 30) &&
        (!cutoff || a.date >= cutoff),
    )
  }, [alerts, activity, region, timeFilter])

  const severityCounts = useMemo(
    () => ({
      critica: preFiltered.filter((a) => a.severity === "critica").length,
      alta: preFiltered.filter((a) => a.severity === "alta").length,
      media: preFiltered.filter((a) => a.severity === "media").length,
    }),
    [preFiltered],
  )

  // Final filtered set (table + KPIs)
  const filtered = useMemo(
    () =>
      severityFilter === "all"
        ? preFiltered
        : preFiltered.filter((a) => a.severity === severityFilter),
    [preFiltered, severityFilter],
  )

  const visibleOnMap = useMemo(
    () => filtered.filter((a) => !hiddenIds.has(a.id)),
    [filtered, hiddenIds],
  )

  const kpis = useMemo(() => {
    const total = filtered.length
    const avgConfidence = filtered.length
      ? Math.round(
          filtered.reduce((sum, a) => sum + a.confidence, 0) / filtered.length,
        )
      : 0
    const wdpaCount = filtered.filter((a) => a.wdpa).length
    return { total, avgConfidence, wdpaCount }
  }, [filtered, summary])

  const selected = useMemo(
    () => visibleOnMap.find((a) => a.id === selectedId) ?? null,
    [visibleOnMap, selectedId],
  )

  const handleSelect = useCallback((alert: Alert) => {
    setSelectedId((prev) => (prev === alert.id ? null : alert.id))
  }, [])

  const handleActivityChange = useCallback((value: ActivityFilter) => {
    setActivity(value)
    setSelectedId(null)
  }, [])

  const handleRegionChange = useCallback((value: RegionFilter) => {
    setRegion(value)
    setSelectedId(null)
  }, [])

  const handleSeverityChange = useCallback((value: SeverityFilter) => {
    setSeverityFilter(value)
    setSelectedId(null)
  }, [])

  const handleTimeChange = useCallback((value: TimeFilter) => {
    setTimeFilter(value)
    setSelectedId(null)
  }, [])

  const handleToggleVisibility = useCallback(
    (id: string) => {
      setHiddenIds((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else {
          next.add(id)
          if (selectedId === id) setSelectedId(null)
        }
        return next
      })
    },
    [selectedId],
  )

  const handleExportCSV = useCallback(() => {
    exportAlertsCSV(filtered)
  }, [filtered])

  return (
    <main className="flex h-screen w-full overflow-hidden">
      <ControlPanel
        activity={activity}
        region={region}
        severityFilter={severityFilter}
        severityCounts={severityCounts}
        timeFilter={timeFilter}
        alerts={filtered}
        total={kpis.total}
        avgConfidence={kpis.avgConfidence}
        wdpaCount={kpis.wdpaCount}
        selectedId={selectedId}
        hiddenIds={hiddenIds}
        error={error}
        loading={loading}
        lastSync={lastSync}
        onActivityChange={handleActivityChange}
        onRegionChange={handleRegionChange}
        onSeverityChange={handleSeverityChange}
        onTimeChange={handleTimeChange}
        onSelect={handleSelect}
        onToggleVisibility={handleToggleVisibility}
        onExportCSV={handleExportCSV}
      />
      <MapViewport
        alerts={visibleOnMap}
        region={region}
        selected={selected}
        onSelect={handleSelect}
        onClosePopup={() => setSelectedId(null)}
      />
    </main>
  )
}
