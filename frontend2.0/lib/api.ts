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
}

interface ApiGeoJSONCollection {
  type: string
  features: Array<{
    type: string
    geometry: { type: string; coordinates: number[] }
    properties: ApiAlertProperties
  }>
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'

const ACTIVITY_MAP: Record<string, ActivityType> = {
  deforestacion: 'deforestacion',
  mineria: 'mineria',
  incendio: 'incendios',
  incendios: 'incendios',
  agricultura: 'cultivos',
  asentamiento: 'cultivos',
  normal: 'deforestacion',
}

function detectRegion(lat: number, lon: number): Region {
  if (lat > -4 && lat < 12 && lon > -79 && lon < -66) return 'colombia'
  if (lat > -18 && lat < 0 && lon > -82 && lon < -68) return 'peru'
  if (lat > -22 && lat < -9 && lon > -70 && lon < -57) return 'bolivia'
  return 'brasil'
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
    type: ACTIVITY_MAP[props.actividad ?? ''] ?? 'deforestacion',
    lat,
    lon,
    date: props.detection_date ?? new Date().toISOString().split('T')[0],
    confidence: Math.round((props.confianza ?? 0) * 100) / 100,
    verdict: mapVerdict(props.veredicto),
    severity: mapSeverity(props.severity ?? props.severidad),
    region: detectRegion(lat, lon),
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

export async function triggerAnalysis(region: string): Promise<void> {
  const res = await fetch(`${API_BASE}/run-analysis?region=${encodeURIComponent(region)}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
}
