"use client"

import { cn } from "@/lib/utils"
import { Activity, Flame, Gauge, ShieldAlert, Target, Wind, Zap } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ActivityType, Alert } from "@/lib/sentinel-data"

interface Kpi {
  label: string
  value: string
  hint: string
  icon: LucideIcon
  tone: "primary" | "destructive" | "neutral"
}

const TONE: Record<Kpi["tone"], string> = {
  primary: "text-primary",
  destructive: "text-destructive",
  neutral: "text-foreground",
}

function computeFireKpis(alerts: Alert[]): Kpi[] {
  const confirmed = alerts.filter((a) => a.tier === "confirmed")

  const maxFrp = alerts.reduce((m, a) => Math.max(m, a.max_frp ?? 0), 0)

  const fwiCounts = alerts.reduce<Record<string, number>>((acc, a) => {
    if (a.fire_weather_index) acc[a.fire_weather_index] = (acc[a.fire_weather_index] ?? 0) + 1
    return acc
  }, {})
  const topFwi = Object.entries(fwiCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "—"

  const scores = alerts.map((a) => a.intentionality_score).filter((s): s is number => s != null)
  const avgRisk = scores.length ? Math.round(scores.reduce((s, v) => s + v, 0) / scores.length) : 0

  return [
    {
      label: "Eventos Activos",
      value: confirmed.length.toString(),
      hint: "alertas tier=confirmed",
      icon: Flame,
      tone: "destructive",
    },
    {
      label: "FRP Máximo",
      value: maxFrp > 0 ? `${maxFrp.toFixed(0)} MW` : "—",
      hint: "potencia radiativa máx.",
      icon: Zap,
      tone: "destructive",
    },
    {
      label: "Índice Meteorológico",
      value: topFwi,
      hint: "fire weather index más frecuente",
      icon: Wind,
      tone: "neutral",
    },
    {
      label: "Riesgo Promedio",
      value: scores.length ? `${avgRisk}%` : "—",
      hint: "score intencionalidad medio",
      icon: Target,
      tone: scores.length && avgRisk >= 60 ? "destructive" : "primary",
    },
  ]
}

export function KpiCards({
  total,
  avgConfidence,
  wdpaCount,
  alerts,
  activity,
}: {
  total: number
  avgConfidence: number
  wdpaCount: number
  alerts: Alert[]
  activity: ActivityType | "all"
}) {
  const isFireTab = activity === "incendios"

  const defaultKpis: Kpi[] = [
    {
      label: "Alertas Totales",
      value: total.toString(),
      hint: "en la región y filtro activos",
      icon: Activity,
      tone: "neutral",
    },
    {
      label: "Certeza Promedio",
      value: `${avgConfidence}%`,
      hint: "confianza del modelo",
      icon: Gauge,
      tone: "primary",
    },
    {
      label: "Áreas Protegidas",
      value: wdpaCount.toString(),
      hint: "cruces con polígonos WDPA",
      icon: ShieldAlert,
      tone: "destructive",
    },
  ]

  const kpis = isFireTab ? computeFireKpis(alerts) : defaultKpis

  return (
    <div className={cn("grid gap-3", isFireTab ? "grid-cols-4" : "grid-cols-3")}>
      {kpis.map((kpi) => {
        const Icon = kpi.icon
        return (
          <div
            key={kpi.label}
            className="rounded-xl border border-border bg-card p-4"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">
                {kpi.label}
              </span>
              <Icon
                className={cn("size-4", TONE[kpi.tone])}
                aria-hidden
              />
            </div>
            <p
              className={cn(
                "mt-3 font-mono text-3xl font-semibold tabular-nums tracking-tight",
                TONE[kpi.tone],
              )}
            >
              {kpi.value}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">{kpi.hint}</p>
          </div>
        )
      })}
    </div>
  )
}
