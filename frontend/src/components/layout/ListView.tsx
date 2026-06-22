import { FC, useState, useMemo } from 'react'
import { AlertProperties, Activity, Severity } from '../../types'
import { normSev, sevColor, ACTIVITY_LABELS, exportAlertsCSV } from '../../utils'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'

const PAGE_SIZE = 50

type SortKey = 'severity' | 'actividad' | 'area_ha' | 'confianza' | 'detection_date' | 'veredicto'
type SortDir = 'asc' | 'desc'

interface ListViewProps {
  alerts: AlertProperties[]
  onSelectAlert: (alert: AlertProperties) => void
  filterAct: Set<Activity | 'all'>
  filterSev: Set<Severity | 'all'>
  filterVer: 'all' | 'ILEGAL' | 'Requiere'
  onToggleAct: (key: Activity | 'all') => void
  onToggleSev: (key: Severity | 'all') => void
  onChangeVer: (val: string) => void
}

const actOrder: (Activity | 'all')[] = ['all', 'deforestacion', 'mineria', 'agricultura', 'incendio', 'asentamiento', 'normal']
const sevOrder: (Severity | 'all')[] = ['all', 'alta', 'media', 'baja']
const sevLabels: Record<Severity | 'all', string> = { all: 'Todas', alta: 'Alta', media: 'Media', baja: 'Baja' }
const sevColors: Record<Severity | 'all', string> = { all: 'var(--text-sec)', alta: 'var(--sev-alta)', media: 'var(--sev-media)', baja: 'var(--sev-baja)' }
const sevRankMap: Record<string, number> = { alta: 0, media: 1, baja: 2 }

export const ListView: FC<ListViewProps> = ({
  alerts,
  onSelectAlert,
  filterAct,
  filterSev,
  filterVer,
  onToggleAct,
  onToggleSev,
  onChangeVer,
}) => {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'severity', dir: 'asc' })
  const [page, setPage] = useState(0)

  const actCounts: Record<string, number> = {}
  alerts.forEach((a) => { actCounts[a.actividad || 'normal'] = (actCounts[a.actividad || 'normal'] || 0) + 1 })

  const sorted = useMemo(() => {
    const arr = [...alerts]
    arr.sort((a, b) => {
      let cmp = 0
      switch (sort.key) {
        case 'severity':
          cmp = (sevRankMap[normSev(a.severity)] ?? 2) - (sevRankMap[normSev(b.severity)] ?? 2)
          break
        case 'actividad':
          cmp = (a.actividad ?? '').localeCompare(b.actividad ?? '')
          break
        case 'area_ha':
          cmp = (a.area_ha ?? 0) - (b.area_ha ?? 0)
          break
        case 'confianza':
          cmp = (a.confianza ?? 0) - (b.confianza ?? 0)
          break
        case 'detection_date':
          cmp = (a.detection_date ?? '').localeCompare(b.detection_date ?? '')
          break
        case 'veredicto':
          cmp = (a.veredicto ?? '').localeCompare(b.veredicto ?? '')
          break
      }
      return sort.dir === 'asc' ? cmp : -cmp
    })
    return arr
  }, [alerts, sort])

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)
  const pageAlerts = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  function toggleSort(key: SortKey) {
    setSort((prev) => prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' })
    setPage(0)
  }

  function SortArrow({ k }: { k: SortKey }) {
    if (sort.key !== k) return <span style={{ color: 'var(--text-muted)', marginLeft: '3px' }}>↕</span>
    return <span style={{ color: 'var(--accent)', marginLeft: '3px' }}>{sort.dir === 'asc' ? '↑' : '↓'}</span>
  }

  const thStyle = (k: SortKey): React.CSSProperties => ({
    padding: '8px 10px',
    fontSize: '11px',
    color: sort.key === k ? 'var(--text-pri)' : 'var(--text-muted)',
    cursor: 'pointer',
    userSelect: 'none',
    whiteSpace: 'nowrap',
  })

  return (
    <div style={{ position: 'fixed', inset: 0, top: 'var(--nav-h)', background: 'var(--bg-base)', display: 'flex', zIndex: 70 }}>
      {/* Filter sidebar */}
      <div
        style={{
          width: '220px',
          flexShrink: 0,
          background: 'var(--bg-surface)',
          borderRight: '1px solid var(--border)',
          overflowY: 'auto',
          padding: '10px 12px',
        }}
      >
        <div style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px' }}>
          Actividad
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', marginBottom: '16px' }}>
          {actOrder.map((key) => {
            const label = key === 'all' ? 'Todas' : ACTIVITY_LABELS[key]?.label || key
            const cnt = key === 'all' ? alerts.length : (actCounts[key] ?? 0)
            return (
              <div
                key={key}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 4px', borderRadius: '4px', cursor: 'pointer' }}
                onClick={() => onToggleAct(key)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'var(--bg-hover)' }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
              >
                <Checkbox
                  id={`lv-act-${key}`}
                  checked={filterAct.has(key)}
                  onCheckedChange={() => onToggleAct(key)}
                  onClick={(e) => e.stopPropagation()}
                  style={{ width: '14px', height: '14px' }}
                />
                <Label htmlFor={`lv-act-${key}`} style={{ flex: 1, fontSize: '12px', fontWeight: 400, color: 'var(--text-pri)', cursor: 'pointer' }}>
                  {label}
                </Label>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{cnt}</span>
              </div>
            )
          })}
        </div>

        <div style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px' }}>
          Severidad
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', marginBottom: '16px' }}>
          {sevOrder.map((key) => (
            <div
              key={key}
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 4px', borderRadius: '4px', cursor: 'pointer' }}
              onClick={() => onToggleSev(key as Severity | 'all')}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'var(--bg-hover)' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              <Checkbox
                id={`lv-sev-${key}`}
                checked={filterSev.has(key)}
                onCheckedChange={() => onToggleSev(key as Severity | 'all')}
                onClick={(e) => e.stopPropagation()}
                style={{ width: '14px', height: '14px' }}
              />
              <Label htmlFor={`lv-sev-${key}`} style={{ flex: 1, fontSize: '12px', fontWeight: 400, color: sevColors[key], cursor: 'pointer' }}>
                {sevLabels[key]}
              </Label>
            </div>
          ))}
        </div>

        <div style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px' }}>
          Veredicto
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
          {([
            { value: 'all', label: 'Todos', color: 'var(--text-sec)' },
            { value: 'ILEGAL', label: 'ILEGAL', color: 'var(--sev-alta)' },
            { value: 'Requiere', label: 'Requiere verificación', color: 'var(--sev-media)' },
          ] as const).map(({ value, label, color }) => {
            const active = filterVer === value
            return (
              <div
                key={value}
                onClick={() => onChangeVer(value)}
                style={{
                  display: 'flex', alignItems: 'center', gap: '8px',
                  padding: '5px 4px', borderRadius: '4px', cursor: 'pointer',
                  background: active ? 'var(--bg-hover)' : 'transparent',
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'var(--bg-hover)' }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = active ? 'var(--bg-hover)' : 'transparent' }}
              >
                <span style={{
                  width: '14px', height: '14px', flexShrink: 0,
                  borderRadius: '50%',
                  border: `1.5px solid ${active ? color : 'var(--border)'}`,
                  background: active ? color : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'all .12s',
                }}>
                  {active && <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#fff', display: 'block' }} />}
                </span>
                <span style={{ fontSize: '12px', color: active ? color : 'var(--text-pri)', fontWeight: active ? 500 : 400 }}>
                  {label}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Main table area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 16px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-surface)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-sec)' }}>{sorted.length} alertas</span>
            {totalPages > 1 && (
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Pág. {page + 1} / {totalPages}</span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => exportAlertsCSV(sorted)}
            style={{ fontSize: '12px', height: '28px', background: 'transparent', borderColor: 'var(--border)', color: 'var(--text-sec)' }}
          >
            Exportar CSV
          </Button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          <Table>
            <TableHeader style={{ position: 'sticky', top: 0, background: 'var(--bg-surface)', zIndex: 10 }}>
              <TableRow style={{ borderColor: 'var(--border)' }}>
                <TableHead style={thStyle('severity')} onClick={() => toggleSort('severity')}>
                  Sev <SortArrow k="severity" />
                </TableHead>
                <TableHead style={thStyle('actividad')} onClick={() => toggleSort('actividad')}>
                  Actividad <SortArrow k="actividad" />
                </TableHead>
                <TableHead style={{ ...thStyle('area_ha'), textAlign: 'right' }} onClick={() => toggleSort('area_ha')}>
                  Área (ha) <SortArrow k="area_ha" />
                </TableHead>
                <TableHead style={{ ...thStyle('confianza'), textAlign: 'right' }} onClick={() => toggleSort('confianza')}>
                  Conf. <SortArrow k="confianza" />
                </TableHead>
                <TableHead style={{ padding: '8px 10px', fontSize: '11px', color: 'var(--text-muted)' }}>
                  Coordenadas
                </TableHead>
                <TableHead style={thStyle('detection_date')} onClick={() => toggleSort('detection_date')}>
                  Fecha <SortArrow k="detection_date" />
                </TableHead>
                <TableHead style={thStyle('veredicto')} onClick={() => toggleSort('veredicto')}>
                  Veredicto <SortArrow k="veredicto" />
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageAlerts.map((a) => {
                const sev = normSev(a.severity)
                const color = sevColor(sev)
                const actLabel = ACTIVITY_LABELS[a.actividad || 'normal']?.label || a.actividad || '—'
                const lat = typeof a.lat === 'string' ? parseFloat(a.lat) : a.lat
                const lon = typeof a.lon === 'string' ? parseFloat(a.lon) : a.lon
                const isIlegal = a.veredicto === 'ILEGAL'
                const isReq = (a.veredicto || '').startsWith('Requiere')

                return (
                  <TableRow
                    key={a.id}
                    onClick={() => onSelectAlert(a)}
                    style={{ cursor: 'pointer', borderColor: 'var(--border-sub)' }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'var(--bg-hover)' }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'transparent' }}
                  >
                    <TableCell style={{ padding: '7px 10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: color, flexShrink: 0, display: 'block' }} />
                        <span style={{ fontSize: '11px', color, fontWeight: 600 }}>
                          {sev.charAt(0).toUpperCase() + sev.slice(1)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell style={{ padding: '7px 10px', fontSize: '13px', fontWeight: 500, color: 'var(--text-pri)' }}>
                      {actLabel}
                    </TableCell>
                    <TableCell style={{ padding: '7px 10px', fontSize: '12px', fontFamily: 'var(--font-mono)', textAlign: 'right', color: 'var(--text-sec)' }}>
                      {a.area_ha != null ? a.area_ha.toFixed(1) : '—'}
                    </TableCell>
                    <TableCell style={{ padding: '7px 10px', fontSize: '12px', fontFamily: 'var(--font-mono)', textAlign: 'right', color: 'var(--text-sec)' }}>
                      {a.confianza != null ? `${Math.round(a.confianza * 100)}%` : '—'}
                    </TableCell>
                    <TableCell style={{ padding: '7px 10px', fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                      {lat.toFixed(4)}, {lon.toFixed(4)}
                    </TableCell>
                    <TableCell style={{ padding: '7px 10px', fontSize: '12px', color: 'var(--text-sec)' }}>
                      {a.detection_date ?? '—'}
                    </TableCell>
                    <TableCell style={{ padding: '7px 10px' }}>
                      {(isIlegal || isReq) ? (
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
                      ) : (
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>—</span>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>

        {totalPages > 1 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              padding: '8px',
              borderTop: '1px solid var(--border)',
              background: 'var(--bg-surface)',
            }}
          >
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              style={{ fontSize: '12px', height: '28px', background: 'transparent', borderColor: 'var(--border)', color: 'var(--text-sec)' }}
            >
              ← Anterior
            </Button>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{page + 1} / {totalPages}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              style={{ fontSize: '12px', height: '28px', background: 'transparent', borderColor: 'var(--border)', color: 'var(--text-sec)' }}
            >
              Siguiente →
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
