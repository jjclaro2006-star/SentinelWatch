export type Severity = 'alta' | 'media' | 'baja'
export type Activity = 'deforestacion' | 'mineria' | 'agricultura' | 'incendio' | 'asentamiento' | 'normal'
export type ViewMode = 'globe' | 'map' | 'satellite' | 'list'

export interface AlertProperties {
  id: string
  lat: string | number
  lon: string | number
  severity?: string
  severidad?: string
  actividad?: Activity
  veredicto?: string
  area_ha?: number | null
  confianza?: number | null
  ndvi_change?: number | null
  detection_date?: string
}

export interface AlertSummary {
  total_alerts: number
  severity: Record<string, number>
  detection_date: string | null
  source_files: string[]
}

export interface GeoJSONFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: number[] }
  properties: AlertProperties
}

export interface GeoJSONCollection {
  type: 'FeatureCollection'
  features: GeoJSONFeature[]
}

export interface AppState {
  mode: ViewMode
  alerts: AlertProperties[]
  filtered: AlertProperties[]
  selected: AlertProperties | null
  filterAct: Set<Activity | 'all'>
  filterSev: Set<Severity | 'all'>
  filterVer: 'all' | 'ILEGAL' | 'Requiere'
  sidebarOpen: boolean
  summary: AlertSummary | null
  error: string | null
}
