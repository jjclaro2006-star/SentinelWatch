import { Severity, Activity } from './types'

export function normSev(raw?: string): Severity {
  const s = (raw ?? '').toLowerCase()
  if (s === 'high' || s === 'alta') return 'alta'
  if (s === 'medium' || s === 'media') return 'media'
  return 'baja'
}

export function sevColor(sev: Severity): string {
  switch (sev) {
    case 'alta':
      return '#f85149'
    case 'media':
      return '#d29922'
    case 'baja':
      return '#3fb950'
  }
}

export function exportAlertsCSV(alerts: import('./types').AlertProperties[], filename?: string) {
  const headers = ['ID', 'Latitud', 'Longitud', 'Actividad', 'Severidad', 'Area_ha', 'Confianza', 'NDVI_change', 'Fecha', 'Veredicto']
  const rows = alerts.map((a) => [
    a.id, a.lat, a.lon, a.actividad ?? '', a.severity ?? '',
    a.area_ha ?? '', a.confianza ?? '', a.ndvi_change ?? '',
    a.detection_date ?? '', a.veredicto ?? '',
  ])
  const csv = [headers, ...rows].map((r) => r.join(',')).join('\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename ?? `sentinelwatch_${new Date().toISOString().split('T')[0]}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function sevRank(sev: Severity): number {
  switch (sev) {
    case 'alta':
      return 0
    case 'media':
      return 1
    case 'baja':
      return 2
  }
}

export function formatCoord(value: number, decimals: number = 5): string {
  return value.toFixed(decimals).padStart(decimals + 4, '0')
}

export function formatAltitude(meters: number): string {
  if (meters >= 1000) {
    return `ALT ${(meters / 1000).toFixed(0)} km`
  }
  return `ALT ${Math.round(meters)} m`
}

export function truncateId(id: string, maxLen: number = 22): string {
  return id.length > maxLen ? id.slice(0, maxLen) + '…' : id
}

// SVG markers as data URIs (for potential future use; canvas is primary)
export function generateDotMarkerSVG(color: string): string {
  const svg = `<svg width="14" height="14" viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg">
    <circle cx="7" cy="7" r="5" fill="${color}" opacity="0.25"/>
    <circle cx="7" cy="7" r="3" fill="${color}" opacity="0.9"/>
    <circle cx="7" cy="7" r="1.2" fill="#fff" opacity="0.85"/>
  </svg>`
  return 'data:image/svg+xml;base64,' + btoa(svg)
}

export function generateIntelMarkerSVG(color: string): string {
  const svg = `<svg width="34" height="34" viewBox="0 0 34 34" xmlns="http://www.w3.org/2000/svg">
    <circle cx="17" cy="17" r="10" fill="none" stroke="${color}" stroke-width="1.5"/>
    <circle cx="17" cy="17" r="2" fill="${color}"/>
    <line x1="17" y1="2" x2="17" y2="5" stroke="${color}" stroke-width="1"/>
    <line x1="17" y1="29" x2="17" y2="32" stroke="${color}" stroke-width="1"/>
    <line x1="2" y1="17" x2="5" y2="17" stroke="${color}" stroke-width="1"/>
    <line x1="29" y1="17" x2="32" y2="17" stroke="${color}" stroke-width="1"/>
  </svg>`
  return 'data:image/svg+xml;base64,' + btoa(svg)
}

export const ACTIVITY_LABELS: Record<Activity, { label: string; color: string }> = {
  deforestacion: { label: 'Deforestación', color: '#EF4444' },
  mineria: { label: 'Minería', color: '#F97316' },
  agricultura: { label: 'Agricultura', color: '#EAB308' },
  incendio: { label: 'Incendio', color: '#F59E0B' },
  asentamiento: { label: 'Asentamiento', color: '#A78BFA' },
  normal: { label: 'Normal', color: '#5A6A80' },
}
