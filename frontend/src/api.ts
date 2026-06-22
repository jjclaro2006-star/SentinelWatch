import { GeoJSONCollection, AlertSummary } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export async function fetchAlerts(): Promise<GeoJSONCollection> {
  try {
    const res = await fetch(`${API_BASE}/alerts`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    const data = await res.json()
    // Filter for mining activity only (as per spec)
    if (data.features) {
      data.features = data.features.filter(
        (f: any) => (f.properties?.actividad || '').toLowerCase() === 'mineria'
      )
    }
    return data
  } catch (err) {
    console.error('fetchAlerts error:', err)
    throw err
  }
}

export async function fetchSummary(): Promise<AlertSummary> {
  try {
    const res = await fetch(`${API_BASE}/alerts/summary`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
    return await res.json()
  } catch (err) {
    console.error('fetchSummary error:', err)
    throw err
  }
}

export async function triggerAnalysis(region: string): Promise<void> {
  try {
    const res = await fetch(`${API_BASE}/run-analysis?region=${encodeURIComponent(region)}`, {
      method: 'POST',
    })
    if (!res.ok) throw new Error(`API error: ${res.status}`)
  } catch (err) {
    console.error('triggerAnalysis error:', err)
    throw err
  }
}
