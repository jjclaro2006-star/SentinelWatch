import type { Alert, AlertSummary, ActivityType, Region, Severity, Verdict } from './sentinel-data'

interface ApiAlertProperties {
  id: string
  lat: string | number
  lon: string | number
  severity?: string
  severidad?: string
  actividad?: string
  veredicto?: string
  area_ha?: number | null
  confianza?: number | null
  ndvi_change?: number | null
  detection_date?: string
  _source_region?: string
}

interface ApiGeoJSONCollection {
  type: string
  features: Array<{
    type: string
    geometry: { type: string; coordinates: number[] }
    properties: ApiAlertProperties
  }>
}

interface FireEventProperties {
  event_id: string
  tier: "confirmed" | "preliminary" | "unconfirmed"
  detection_count: number
  max_frp: number
  duration_hours: number
  start_date: string
  last_seen: string
  sources: string[]
  wdpa_overlap?: boolean
  intentionality_score?: number
  intentionality_level?: string
  legal_risk_score?: number
  spread_summary?: string
  fire_weather_index?: string
}

interface FireEventFeature {
  type: string
  geometry: { type: string; coordinates: [number, number] }
  properties: FireEventProperties
}

interface FireGeoJSONCollection {
  type: string
  features: FireEventFeature[]
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'

const ACTIVITY_MAP: Record<string, ActivityType> = {
  mineria:   'mineria',
  incendio:  'incendios',
  incendios: 'incendios',
}

function mapSourceRegion(sourceRegion?: string): Region {
  if (!sourceRegion) return 'peru'
  if (sourceRegion.startsWith('brasil')) return 'brasil'
  if (sourceRegion === 'bolivia') return 'bolivia'
  if (sourceRegion === 'colombia') return 'colombia'
  if (sourceRegion === 'biobio' || sourceRegion.startsWith('chile')) return 'biobio'
  return 'peru'
}

function computeMapPosition(lat: number, lon: number): { x: number; y: number } {
  const x = Math.round(Math.min(95, Math.max(5, ((lon + 80) / 25) * 90 + 5)))
  const y = Math.round(Math.min(95, Math.max(5, ((8 - lat) / 30) * 90 + 5)))
  return { x, y }
}

function mapSeverity(raw?: string): Severity {
  const s = (raw ?? '').toLowerCase()
  if (s === 'critica' || s === 'critical') return 'critica'
  if (s === 'alta' || s === 'high') return 'alta'
  return 'media'
}

function mapVerdict(raw?: string): Verdict {
  if ((raw ?? '').toUpperCase() === 'ILEGAL') return 'ILEGAL'
  return 'VERIFICAR'
}

export function mapApiAlertToAlert(props: ApiAlertProperties): Alert {
  const lat = typeof props.lat === 'string' ? parseFloat(props.lat) : (props.lat ?? 0)
  const lon = typeof props.lon === 'string' ? parseFloat(props.lon) : (props.lon ?? 0)
  const { x, y } = computeMapPosition(lat, lon)
  return {
    id: props.id,
    type: ACTIVITY_MAP[props.actividad ?? ''] ?? 'mineria',
    lat,
    lon,
    date: props.detection_date ?? new Date().toISOString().split('T')[0],
    confidence: Math.round((props.confianza ?? 0) * 100) / 100,
    verdict: mapVerdict(props.veredicto),
    severity: mapSeverity(props.severity ?? props.severidad),
    region: mapSourceRegion(props._source_region),
    wdpa: false,
    source: 'Sentinel',
    x,
    y,
    area_ha: props.area_ha,
    ndvi_change: props.ndvi_change,
  }
}

export async function fetchAlerts(): Promise<Alert[]> {
  const res = await fetch(`${API_BASE}/alerts`, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const data: ApiGeoJSONCollection = await res.json()
  return (data.features ?? []).map((f) => mapApiAlertToAlert(f.properties))
}

export async function fetchSummary(): Promise<AlertSummary> {
  const res = await fetch(`${API_BASE}/alerts/summary`, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const _FIRE_TIER_SEVERITY: Record<string, Severity> = {
  confirmed:   "critica",
  preliminary: "alta",
  unconfirmed: "media",
}

export function mapFireEventToAlert(feature: FireEventFeature): Alert {
  const p = feature.properties
  const [lon, lat] = feature.geometry.coordinates
  return {
    id:              p.event_id,
    type:            "incendios",
    lat,
    lon,
    date:            p.start_date,
    confidence:      Math.round(Math.min((p.max_frp ?? 0) / 200, 1) * 100),
    verdict:         p.tier === "confirmed" ? "CONFIRMADO" : "PRELIMINAR",
    severity:        _FIRE_TIER_SEVERITY[p.tier] ?? "media",
    region:          "biobio",
    wdpa:            p.wdpa_overlap ?? false,
    source:          p.sources?.join(", ") || "VIIRS",
    x:               lon,
    y:               lat,
    // Fire-specific fields
    tier:                p.tier,
    max_frp:             p.max_frp,
    duration_hours:      p.duration_hours,
    detection_count:     p.detection_count,
    intentionality_score:  p.intentionality_score,
    intentionality_level:  p.intentionality_level,
    legal_risk_score:      p.legal_risk_score,
    spread_summary:        p.spread_summary,
    fire_weather_index:    p.fire_weather_index,
  }
}

export async function fetchFireEvents(): Promise<FireGeoJSONCollection> {
  const res = await fetch(`${API_BASE}/fire/events`)
  if (!res.ok) return { type: "FeatureCollection", features: [] }
  return res.json()
}

export async function fetchFireStats(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/fire/stats`)
  if (!res.ok) return {}
  return res.json()
}

export async function triggerAnalysis(region: string): Promise<void> {
  const res = await fetch(`${API_BASE}/run-analysis?region=${encodeURIComponent(region)}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
}
