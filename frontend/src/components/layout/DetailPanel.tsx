import { FC, memo } from 'react'
import { AlertProperties } from '../../types'
import { normSev, sevColor, ACTIVITY_LABELS } from '../../utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

interface DetailPanelProps {
  alert: AlertProperties | null
  onClose: () => void
}

const LEGAL_LAYERS = [
  { key: 'wdpa', label: 'Área Protegida WDPA' },
  { key: 'indigenous', label: 'Territorio Indígena' },
  { key: 'concession', label: 'Concesión Minera' },
  { key: 'permit', label: 'Permiso Ambiental' },
  { key: 'buffer', label: 'Zona Buffer 300m' },
]

const DetailPanelInner: FC<DetailPanelProps> = ({ alert: alertProp, onClose }) => {
  if (!alertProp) return null
  const alert = alertProp

  const sev = normSev(alert.severity)
  const sevCol = sevColor(sev)
  const ver = alert.veredicto || ''
  const actLabel = ACTIVITY_LABELS[alert.actividad || 'normal']?.label || alert.actividad || '—'
  const lat = typeof alert.lat === 'string' ? parseFloat(alert.lat) : alert.lat
  const lon = typeof alert.lon === 'string' ? parseFloat(alert.lon) : alert.lon

  const isIlegal = ver === 'ILEGAL'
  const isRequiere = ver.startsWith('Requiere')

  function handleCopyCoords() {
    navigator.clipboard.writeText(`${lat.toFixed(6)}, ${lon.toFixed(6)}`).catch(() => {})
  }

  function handleExportPDF() {
    const el = document.getElementById('sw-print-target')
    if (!el) return
    el.innerHTML = `
      <h2 style="font-size:18px;font-weight:700;margin-bottom:8px">SentinelWatch — Detalle de Alerta</h2>
      <p style="font-size:12px;color:#444;margin-bottom:20px">${alert.id}</p>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <tr><td style="padding:6px 0;color:#666;width:140px">Actividad</td><td>${actLabel}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Severidad</td><td>${sev.toUpperCase()}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Veredicto</td><td>${ver || '—'}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Área</td><td>${alert.area_ha?.toFixed(1) ?? '—'} ha</td></tr>
        <tr><td style="padding:6px 0;color:#666">Confianza</td><td>${alert.confianza != null ? Math.round(alert.confianza * 100) + '%' : '—'}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Δ NDVI</td><td>${alert.ndvi_change?.toFixed(4) ?? '—'}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Fecha</td><td>${alert.detection_date ?? '—'}</td></tr>
        <tr><td style="padding:6px 0;color:#666">Latitud</td><td>${lat.toFixed(6)}° S</td></tr>
        <tr><td style="padding:6px 0;color:#666">Longitud</td><td>${lon.toFixed(6)}° W</td></tr>
      </table>
    `
    el.style.display = 'block'
    window.print()
    el.style.display = 'none'
    el.innerHTML = ''
  }

  const metrics = [
    { label: 'Área', value: alert.area_ha != null ? `${alert.area_ha.toFixed(1)} ha` : '—' },
    { label: 'Confianza', value: alert.confianza != null ? `${Math.round(alert.confianza * 100)}%` : '—' },
    { label: 'Δ NDVI', value: alert.ndvi_change != null ? alert.ndvi_change.toFixed(4) : '—' },
    { label: 'Fecha', value: alert.detection_date ?? '—' },
  ]

  return (
    <>
      <div id="sw-print-target" style={{ display: 'none' }} />
      <div
        style={{
          position: 'fixed',
          top: 'var(--nav-h)',
          right: 0,
          bottom: 0,
          width: '320px',
          zIndex: 90,
          background: 'var(--bg-surface)',
          borderLeft: '1px solid var(--border)',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ padding: '14px 14px 0', flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
            <span style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
              Detalle de Alerta
            </span>
            <button
              onClick={onClose}
              style={{
                width: '24px',
                height: '24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'transparent',
                border: '1px solid var(--border)',
                color: 'var(--text-sec)',
                cursor: 'pointer',
                borderRadius: '4px',
                fontSize: '12px',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--text-sec)' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)' }}
            >
              ✕
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
            <Badge
              style={{
                background: `rgba(${sevCol === '#f85149' ? '248,81,73' : sevCol === '#d29922' ? '210,153,34' : '63,185,80'}, 0.15)`,
                border: `1px solid rgba(${sevCol === '#f85149' ? '248,81,73' : sevCol === '#d29922' ? '210,153,34' : '63,185,80'}, 0.4)`,
                color: sevCol,
                fontSize: '10px',
                fontWeight: 700,
                letterSpacing: '.06em',
              }}
            >
              {sev.toUpperCase()}
            </Badge>
            <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-pri)' }}>{actLabel}</span>
          </div>

          <p style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: '14px', wordBreak: 'break-all' }}>
            {alert.id}
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginBottom: '14px' }}>
            {metrics.map(({ label, value }) => (
              <Card key={label} style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>
                <CardContent style={{ padding: '8px 10px' }}>
                  <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--text-muted)', marginBottom: '3px' }}>
                    {label}
                  </p>
                  <p style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 500, color: 'var(--text-pri)' }}>
                    {value}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginBottom: '14px' }}>
            {[
              { label: 'Latitud', value: `${lat.toFixed(6)}°` },
              { label: 'Longitud', value: `${lon.toFixed(6)}°` },
            ].map(({ label, value }) => (
              <div key={label} style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px 10px' }}>
                <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--text-muted)', marginBottom: '3px' }}>{label}</p>
                <p style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-pri)' }}>{value}</p>
              </div>
            ))}
          </div>

          <Separator style={{ background: 'var(--border)', marginBottom: '14px' }} />

          <div style={{ marginBottom: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Verificación Legal
              </span>
              {(isIlegal || isRequiere) && (
                <Badge
                  style={{
                    background: isIlegal ? 'rgba(248,81,73,.15)' : 'rgba(210,153,34,.15)',
                    border: `1px solid ${isIlegal ? 'rgba(248,81,73,.4)' : 'rgba(210,153,34,.4)'}`,
                    color: isIlegal ? 'var(--sev-alta)' : 'var(--sev-media)',
                    fontSize: '10px',
                    fontWeight: 700,
                    letterSpacing: '.04em',
                  }}
                >
                  {isIlegal ? 'ILEGAL' : 'REQUIERE'}
                </Badge>
              )}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              {LEGAL_LAYERS.map(({ key, label }, i) => {
                const hit = isIlegal ? i % 2 === 0 : i === 2
                return (
                  <div
                    key={key}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '6px 8px',
                      borderRadius: '4px',
                      background: 'var(--bg-elevated)',
                    }}
                  >
                    <span style={{ fontSize: '12px', color: hit ? 'var(--sev-alta)' : 'var(--sev-baja)', flexShrink: 0, width: '14px' }}>
                      {hit ? '✓' : '✗'}
                    </span>
                    <span style={{ fontSize: '12px', color: 'var(--text-pri)', flex: 1 }}>{label}</span>
                    {hit && (
                      <span style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Violación</span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border)', display: 'flex', gap: '8px' }}>
          <Button
            variant="outline"
            size="sm"
            onClick={handleExportPDF}
            style={{ flex: 1, fontSize: '12px', height: '32px', background: 'transparent', borderColor: 'var(--border)', color: 'var(--text-sec)' }}
          >
            Exportar PDF
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleCopyCoords}
            style={{ flex: 1, fontSize: '12px', height: '32px', background: 'transparent', borderColor: 'var(--border)', color: 'var(--text-sec)' }}
          >
            Copiar coords
          </Button>
        </div>
      </div>
    </>
  )
}

export const DetailPanel = memo(DetailPanelInner)
