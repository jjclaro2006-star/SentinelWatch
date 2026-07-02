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
  primary: "text-foreground",
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
      hint: "tier=confirmed",
      icon: Flame,
      tone: "destructive",
    },
    {
      label: "FRP Máximo",
      value: maxFrp > 0 ? `${maxFrp.toFixed(0)} MW` : "—",
      hint: "potencia radiativa",
      icon: Zap,
      tone: "destructive",
    },
    {
      label: "Índice Met.",
      value: topFwi,
      hint: "fire weather index",
      icon: Wind,
      tone: "neutral",
    },
    {
      label: "Riesgo Prom.",
      value: scores.length ? `${avgRisk}%` : "—",
      hint: "intencionalidad",
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
      hint: "en filtro activo",
      icon: Activity,
      tone: "neutral",
    },
    {
      label: "Certeza Prom.",
      value: `${avgConfidence}%`,
      hint: "confianza del modelo",
      icon: Gauge,
      tone: "primary",
    },
    {
      label: "Áreas Prot.",
      value: wdpaCount.toString(),
      hint: "cruces WDPA",
      icon: ShieldAlert,
      tone: "destructive",
    },
  ]

  const kpis = isFireTab ? computeFireKpis(alerts) : defaultKpis

  return (
    <div className={cn("grid gap-2.5 shrink-0", isFireTab ? "grid-cols-4" : "grid-cols-3")}>
      {kpis.map((kpi) => {
        const Icon = kpi.icon
        return (
          <div
            key={kpi.label}
            className="rounded-[11px] border border-white/[0.09] p-3.5"
            style={{
              background:
                "linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.018))",
            }}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-muted-foreground leading-tight">
                {kpi.label}
              </span>
              <Icon
                className={cn("size-3.5 shrink-0", TONE[kpi.tone])}
                aria-hidden
              />
            </div>
            <p
              className={cn(
                "mt-2.5 font-mono tabular-nums tracking-tight",
                isFireTab ? "text-xl font-semibold" : "text-3xl font-semibold",
                TONE[kpi.tone],
              )}
            >
              {kpi.value}
            </p>
            <p className="mt-1 font-mono text-[9px] tracking-[0.06em] text-muted-foreground">
              {kpi.hint}
            </p>
          </div>
        )
      })}
    </div>
  )
}
