"use client"

import { cn } from "@/lib/utils"
import { Activity, Gauge, ShieldAlert } from "lucide-react"
import type { LucideIcon } from "lucide-react"

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

export function KpiCards({
  total,
  avgConfidence,
  wdpaCount,
}: {
  total: number
  avgConfidence: number
  wdpaCount: number
}) {
  const kpis: Kpi[] = [
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

  return (
    <div className="grid grid-cols-3 gap-3">
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
