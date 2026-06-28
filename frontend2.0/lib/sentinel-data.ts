export type ActivityType =
  | "mineria"
  | "deforestacion"
  | "incendios"
  | "cultivos"

export type Region = "colombia" | "peru" | "brasil" | "bolivia" | "biobio"

export type Verdict = "ILEGAL" | "VERIFICAR" | "CONFIRMADO" | "PRELIMINAR"

export type Severity = "critica" | "alta" | "media"

export interface Alert {
  id: string
  type: ActivityType
  lat: number
  lon: number
  date: string
  confidence: number
  verdict: Verdict
  severity: Severity
  region: Region
  wdpa: boolean
  wdpaName?: string
  source: string
  x: number
  y: number
  area_ha?: number | null
  ndvi_change?: number | null
  // Module A fire-specific fields
  tier?: "confirmed" | "preliminary" | "unconfirmed"
  max_frp?: number
  duration_hours?: number
  detection_count?: number
  intentionality_score?: number
  intentionality_level?: string
  legal_risk_score?: number
  spread_summary?: string
  fire_weather_index?: string
}

export interface AlertSummary {
  total_alerts: number
  severity: Record<string, number>
  detection_date: string | null
  source_files: string[]
}

export const ACTIVITY_LABELS: Record<ActivityType, string> = {
  mineria: "Minería Ilegal",
  deforestacion: "Deforestación",
  incendios: "Incendios",
  cultivos: "Cultivos Ilícitos",
}

export const REGION_LABELS: Record<Region, string> = {
  colombia: "Amazonas — Colombia",
  peru: "Amazonas — Perú",
  brasil: "Amazonas — Brasil",
  bolivia: "Amazonas — Bolivia",
  biobio: "Chile — Biobío",
}

export const SEVERITY_META: Record<
  Severity,
  { label: string; className: string }
> = {
  critica: {
    label: "Crítica",
    className: "bg-destructive/15 text-destructive border-destructive/30",
  },
  alta: {
    label: "Alta",
    className:
      "bg-chart-3/15 text-chart-3 border-chart-3/30 [color:oklch(0.82_0.15_80)]",
  },
  media: {
    label: "Media",
    className: "bg-primary/15 text-primary border-primary/30",
  },
}
