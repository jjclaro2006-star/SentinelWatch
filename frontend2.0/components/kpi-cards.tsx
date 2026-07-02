"use client"

import { cn } from "@/lib/utils"
import { Activity, AlertTriangle, Flame, Gauge, ShieldAlert, Target, Wind, Zap } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ActivityType, Alert, Region } from "@/lib/sentinel-data"

interface Kpi {
  label: string
  value: string
  hint: string
  icon: LucideIcon
  tone: "primary" | "destructive" | "neutral"
  bars: number[]
}

const TONE: Record<Kpi["tone"], string> = {
  primary: "text-foreground",
  destructive: "text-destructive",
  neutral: "text-foreground",
}

function MiniBarChart({ values }: { values: number[] }) {
  const max = Math.max(...values, 1)
  return (
    <div className="mt-3 flex h-[22px] items-end gap-[2px]">
      {values.map((v, i) => (
        <div
          key={i}
          className="flex-1 rounded-[1px] bg-white/[0.14]"
          style={{ height: `${Math.max(15, (v / max) * 100)}%` }}
        />
      ))}
    </div>
  )
}

function confidenceBars(alerts: Alert[]): number[] {
  const bins = Array(12).fill(0)
  for (const a of alerts) {
    const idx = Math.min(11, Math.floor(a.confidence / (100 / 12)))
    bins[idx]++
  }
  return bins
}

function regionBars(alerts: Alert[]): number[] {
  const regions: Region[] = ["peru", "brasil", "bolivia", "colombia", "biobio"]
  const counts = regions.map((r) => alerts.filter((a) => a.region === r).length)
  // pad to 12 bars by repeating
  const bars: number[] = []
  while (bars.length < 12) bars.push(...counts)
  return bars.slice(0, 12)
}

function severityBars(alerts: Alert[]): number[] {
  const c = alerts.filter((a) => a.severity === "critica").length
  const a = alerts.filter((a) => a.severity === "alta").length
  const m = alerts.filter((a) => a.severity === "media").length
  const bars = [c, c, c, c, a, a, a, a, m, m, m, m]
  return bars
}

function typeBars(alerts: Alert[]): number[] {
  const mineria = alerts.filter((a) => a.type === "mineria").length
  const incendios = alerts.filter((a) => a.type === "incendios").length
  const bars: number[] = []
  for (let i = 0; i < 12; i++) bars.push(i < 6 ? mineria : incendios)
  return bars
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
      bars: severityBars(alerts),
    },
    {
      label: "FRP Máximo",
      value: maxFrp > 0 ? `${maxFrp.toFixed(0)} MW` : "—",
      hint: "potencia radiativa",
      icon: Zap,
      tone: "destructive",
      bars: confidenceBars(alerts),
    },
    {
      label: "Índice Met.",
      value: topFwi,
      hint: "fire weather index",
      icon: Wind,
      tone: "neutral",
      bars: regionBars(alerts),
    },
    {
      label: "Riesgo Prom.",
      value: scores.length ? `${avgRisk}%` : "—",
      hint: "intencionalidad",
      icon: Target,
      tone: scores.length && avgRisk >= 60 ? "destructive" : "primary",
      bars: typeBars(alerts),
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

  const illegalCount = alerts.filter((a) => a.verdict === "ILEGAL" || a.verdict === "CONFIRMADO").length

  const defaultKpis: Kpi[] = [
    {
      label: "Alertas Totales",
      value: total.toString(),
      hint: "en filtro activo",
      icon: Activity,
      tone: "neutral",
      bars: severityBars(alerts),
    },
    {
      label: "Certeza Prom.",
      value: `${avgConfidence}%`,
      hint: "confianza del modelo",
      icon: Gauge,
      tone: "primary",
      bars: confidenceBars(alerts),
    },
    {
      label: "Áreas Prot.",
      value: wdpaCount.toString(),
      hint: "cruces WDPA",
      icon: ShieldAlert,
      tone: "destructive",
      bars: regionBars(alerts),
    },
    {
      label: "Alertas Ilegales",
      value: illegalCount.toString(),
      hint: "veredicto ILEGAL",
      icon: AlertTriangle,
      tone: illegalCount > 0 ? "destructive" : "neutral",
      bars: typeBars(alerts),
    },
  ]

  const kpis = isFireTab ? computeFireKpis(alerts) : defaultKpis

  return (
    <div className="grid shrink-0 grid-cols-2 gap-2.5">
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
                "mt-2 font-mono text-2xl font-semibold tabular-nums tracking-tight",
                TONE[kpi.tone],
              )}
            >
              {kpi.value}
            </p>
            <p className="mt-0.5 font-mono text-[9px] tracking-[0.06em] text-muted-foreground">
              {kpi.hint}
            </p>
            <MiniBarChart values={kpi.bars} />
          </div>
        )
      })}
    </div>
  )
}
