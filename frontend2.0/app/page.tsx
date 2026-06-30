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
import type { ActivityType, Alert, Verdict } from "@/lib/sentinel-data"

type ActivityFilter = ActivityType | "all"
type VerdictFilter = Verdict | "all"

export default function Page() {
  const { alerts, summary, error, loading, lastSync } = useAlerts()

  const [activity, setActivity] = useState<ActivityFilter>("mineria")
  const [region, setRegion] = useState<RegionFilter>("peru")
  const [filterVerdict, setFilterVerdict] = useState<VerdictFilter>("all")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set())

  const filtered = useMemo(() => {
    return alerts.filter(
      (a) =>
        (region === "all" || a.region === region) &&
        (activity === "all" || a.type === activity) &&
        (filterVerdict === "all" || a.verdict === filterVerdict) &&
        (a.type !== "mineria" || a.confidence >= 30),
    )
  }, [alerts, activity, region, filterVerdict])

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

  const handleVerdictChange = useCallback((value: VerdictFilter) => {
    setFilterVerdict(value)
    setSelectedId(null)
  }, [])

  const handleToggleVisibility = useCallback((id: string) => {
    setHiddenIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else {
        next.add(id)
        if (selectedId === id) setSelectedId(null)
      }
      return next
    })
  }, [selectedId])

  const handleExportCSV = useCallback(() => {
    exportAlertsCSV(filtered)
  }, [filtered])

  return (
    <main className="flex h-screen w-full overflow-hidden">
      <ControlPanel
        activity={activity}
        region={region}
        filterVerdict={filterVerdict}
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
        onVerdictChange={handleVerdictChange}
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
