"use client"

import { memo, useRef, useState, useCallback } from "react"
import { cn } from "@/lib/utils"
import {
  ACTIVITY_LABELS,
  REGION_LABELS,
  SEVERITY_META,
  type Alert,
} from "@/lib/sentinel-data"
import { Eye, EyeOff, Loader2 } from "lucide-react"

const ROW_HEIGHT = 54
const OVERSCAN   = 5

export const AlertsTable = memo(function AlertsTable({
  alerts,
  selectedId,
  hiddenIds,
  loading,
  onSelect,
  onToggleVisibility,
}: {
  alerts: Alert[]
  selectedId: string | null
  hiddenIds: Set<string>
  loading?: boolean
  onSelect: (alert: Alert) => void
  onToggleVisibility: (id: string) => void
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)

  const onScroll = useCallback(() => {
    setScrollTop(scrollRef.current?.scrollTop ?? 0)
  }, [])

  const viewportHeight = scrollRef.current?.clientHeight ?? 600
  const totalHeight = alerts.length * ROW_HEIGHT

  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
  const endIdx   = Math.min(alerts.length, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + OVERSCAN)
  const visibleAlerts = alerts.slice(startIdx, endIdx)
  const offsetTop = startIdx * ROW_HEIGHT

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-[11px] border border-white/[0.07]">
      {/* Header */}
      <div className="grid grid-cols-[1.4fr_1fr_1.1fr_1.2fr_auto] gap-2 border-b border-white/[0.07] bg-white/[0.03] px-4 py-2.5 font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
        <span>ID / Tipo</span>
        <span>Región</span>
        <span>Fecha</span>
        <span>Veredicto</span>
        <span className="sr-only">Visibilidad</span>
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {loading && (
          <div className="flex items-center justify-center gap-2 px-4 py-10 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Cargando alertas…
          </div>
        )}
        {!loading && alerts.length === 0 && (
          <p className="px-4 py-10 text-center font-mono text-[11px] text-muted-foreground">
            No hay alertas para los filtros seleccionados.
          </p>
        )}
        {!loading && alerts.length > 0 && (
          <div style={{ height: totalHeight, position: "relative" }}>
            <div style={{ position: "absolute", top: offsetTop, left: 0, right: 0 }}>
              {visibleAlerts.map((alert) => {
                const severity = SEVERITY_META[alert.severity]
                const selected = selectedId === alert.id
                const hidden = hiddenIds.has(alert.id)
                return (
                  <button
                    key={alert.id}
                    onClick={() => onSelect(alert)}
                    style={{ height: ROW_HEIGHT }}
                    className={cn(
                      "grid w-full grid-cols-[1.4fr_1fr_1.1fr_1.2fr_auto] items-center gap-2 border-b border-white/[0.05] px-4 py-3 text-left transition-colors",
                      selected ? "bg-white/[0.06]" : "hover:bg-white/[0.03]",
                      hidden && "opacity-40",
                    )}
                  >
                    {/* ID / Tipo */}
                    <span className="flex flex-col gap-0.5">
                      <span className="font-mono text-[11px] font-medium text-foreground truncate">
                        {alert.id}
                      </span>
                      <span
                        className={cn(
                          "w-fit rounded border px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-[0.06em]",
                          severity.className,
                        )}
                      >
                        {ACTIVITY_LABELS[alert.type]}
                      </span>
                    </span>

                    {/* Región */}
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {REGION_LABELS[alert.region]}
                    </span>

                    {/* Fecha */}
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {new Date(alert.date).toLocaleDateString("es", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                        timeZone: "UTC",
                      })}
                    </span>

                    {/* Veredicto */}
                    <span>
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full px-2 py-1 font-mono text-[9px] font-semibold uppercase tracking-[0.06em]",
                          alert.verdict === "ILEGAL" || alert.verdict === "CONFIRMADO"
                            ? "bg-destructive/15 text-destructive"
                            : "bg-chart-3/15 text-[color:oklch(0.82_0.15_80)]",
                        )}
                      >
                        <span
                          className={cn(
                            "size-1.5 rounded-full",
                            alert.verdict === "ILEGAL" || alert.verdict === "CONFIRMADO"
                              ? "bg-destructive"
                              : "bg-[oklch(0.82_0.15_80)]",
                          )}
                        />
                        {alert.verdict === "ILEGAL" || alert.verdict === "CONFIRMADO"
                          ? "ILEGAL"
                          : "Verificar"}
                      </span>
                    </span>

                    {/* Visibility */}
                    <span
                      role="button"
                      tabIndex={0}
                      aria-label={
                        hidden
                          ? `Mostrar ${alert.id} en el mapa`
                          : `Ocultar ${alert.id} del mapa`
                      }
                      onClick={(e) => {
                        e.stopPropagation()
                        onToggleVisibility(alert.id)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          e.stopPropagation()
                          onToggleVisibility(alert.id)
                        }
                      }}
                      className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-white/[0.06] hover:text-foreground"
                    >
                      {hidden ? (
                        <EyeOff className="size-4" aria-hidden />
                      ) : (
                        <Eye className="size-4" aria-hidden />
                      )}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
})
