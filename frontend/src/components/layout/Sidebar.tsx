import { FC, useMemo, memo } from 'react'
import { AlertProperties, Activity, Severity } from '../../types'
import { normSev, sevColor, ACTIVITY_LABELS } from '../../utils'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'

interface SidebarProps {
  isOpen: boolean
  alerts: AlertProperties[]
  filtered: AlertProperties[]
  selected: AlertProperties | null
  filterAct: Set<Activity | 'all'>
  filterSev: Set<Severity | 'all'>
  filterVer: 'all' | 'ILEGAL' | 'Requiere'
  onToggleAct: (key: Activity | 'all') => void
  onToggleSev: (key: Severity | 'all') => void
  onChangeVer: (val: string) => void
  onSelectAlert: (alert: AlertProperties) => void
}

function SeverityBar({ alta, media, baja }: { alta: number; media: number; baja: number }) {
  const total = alta + media + baja || 1
  return (
    <div style={{ display: 'flex', gap: '10px', padding: '4px 0' }}>
      {[
        { label: 'Alta', count: alta, color: 'var(--sev-alta)' },
        { label: 'Media', count: media, color: 'var(--sev-media)' },
        { label: 'Baja', count: baja, color: 'var(--sev-baja)' },
      ].map(({ label, count, color }) => (
        <div key={label} style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</span>
            <span style={{ fontSize: '10px', color, fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{count}</span>
          </div>
          <div style={{ height: '3px', borderRadius: '2px', background: 'var(--bg-hover)' }}>
            <div style={{ height: '3px', borderRadius: '2px', width: `${(count / total) * 100}%`, background: color, transition: 'width .3s ease' }} />
          </div>
        </div>
      ))}
    </div>
  )
}

const actOrder: (Activity | 'all')[] = ['all', 'deforestacion', 'mineria', 'agricultura', 'incendio', 'asentamiento', 'normal']
const sevOrder: (Severity | 'all')[] = ['all', 'alta', 'media', 'baja']
const sevLabels: Record<Severity | 'all', string> = { all: 'Todas', alta: 'Alta', media: 'Media', baja: 'Baja' }
const sevColors: Record<Severity | 'all', string> = { all: 'var(--text-sec)', alta: 'var(--sev-alta)', media: 'var(--sev-media)', baja: 'var(--sev-baja)' }

const SidebarInner: FC<SidebarProps> = ({
  isOpen,
  filtered,
  selected,
  filterAct,
  filterSev,
  filterVer,
  onToggleAct,
  onToggleSev,
  onChangeVer,
  onSelectAlert,
}) => {
  const count = useMemo(() => {
    const c = { alta: 0, media: 0, baja: 0 }
    filtered.forEach((a) => { c[normSev(a.severity)]++ })
    return c
  }, [filtered])

  const actCounts = useMemo(() => {
    const c: Record<string, number> = {}
    filtered.forEach((a) => { c[a.actividad || 'normal'] = (c[a.actividad || 'normal'] || 0) + 1 })
    return c
  }, [filtered])

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    const rank: Record<string, number> = { alta: 0, media: 1, baja: 2 }
    return (rank[normSev(a.severity)] ?? 2) - (rank[normSev(b.severity)] ?? 2)
  }), [filtered])

  return (
    <div
      style={{
        position: 'fixed',
        top: 'var(--nav-h)',
        left: 0,
        bottom: 0,
        width: 'var(--sidebar-w)',
        zIndex: 80,
        background: 'var(--bg-surface)',
        borderRight: '1px solid var(--border)',
        transform: isOpen ? 'translateX(0)' : 'translateX(calc(-1 * var(--sidebar-w)))',
        transition: 'transform .25s ease-out',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
        <SeverityBar alta={count.alta} media={count.media} baja={count.baja} />
      </div>

      <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '6px' }}>
          Actividad
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
          {actOrder.map((key) => {
            const label = key === 'all' ? 'Todas' : ACTIVITY_LABELS[key]?.label || key
            const cnt = key === 'all' ? filtered.length : (actCounts[key] ?? 0)
            return (
              <div
                key={key}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 4px', borderRadius: '4px', cursor: 'pointer' }}
                onClick={() => onToggleAct(key)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'var(--bg-hover)' }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
              >
                <Checkbox
                  id={`act-${key}`}
                  checked={filterAct.has(key)}
                  onCheckedChange={() => onToggleAct(key)}
                  onClick={(e) => e.stopPropagation()}
                  style={{ width: '14px', height: '14px' }}
                />
                <Label htmlFor={`act-${key}`} style={{ flex: 1, fontSize: '12px', fontWeight: 400, color: 'var(--text-pri)', cursor: 'pointer' }}>
                  {label}
                </Label>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{cnt}</span>
              </div>
            )
          })}
        </div>
      </div>

      <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '6px' }}>
          Severidad
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
          {sevOrder.map((key) => (
            <div
              key={key}
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 4px', borderRadius: '4px', cursor: 'pointer' }}
              onClick={() => onToggleSev(key as Severity | 'all')}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'var(--bg-hover)' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              <Checkbox
                id={`sev-${key}`}
                checked={filterSev.has(key)}
                onCheckedChange={() => onToggleSev(key as Severity | 'all')}
                onClick={(e) => e.stopPropagation()}
                style={{ width: '14px', height: '14px' }}
              />
              <Label htmlFor={`sev-${key}`} style={{ flex: 1, fontSize: '12px', fontWeight: 400, color: sevColors[key], cursor: 'pointer' }}>
                {sevLabels[key]}
              </Label>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '6px' }}>
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
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '5px 4px',
                  borderRadius: '4px',
                  cursor: 'pointer',
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

      <div style={{ padding: '6px 0 0', flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 12px 6px' }}>
          <span style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
            Alertas
          </span>
          <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--accent)', background: 'var(--accent-dim)', padding: '1px 6px', borderRadius: '3px' }}>
            {filtered.length}
          </span>
        </div>

        <Table>
          <TableHeader>
            <TableRow style={{ borderColor: 'var(--border)' }}>
              <TableHead style={{ width: '20px', padding: '4px 8px', fontSize: '10px', color: 'var(--text-muted)' }}></TableHead>
              <TableHead style={{ padding: '4px 6px', fontSize: '10px', color: 'var(--text-muted)' }}>Actividad</TableHead>
              <TableHead style={{ padding: '4px 6px', fontSize: '10px', color: 'var(--text-muted)', textAlign: 'right' }}>ha</TableHead>
              <TableHead style={{ padding: '4px 6px', fontSize: '10px', color: 'var(--text-muted)' }}>Fecha</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((a) => {
              const sev = normSev(a.severity)
              const isSelected = selected?.id === a.id
              const actLabel = ACTIVITY_LABELS[a.actividad || 'normal']?.label || a.actividad || '—'
              const area = a.area_ha != null ? a.area_ha.toFixed(1) : '—'
              const color = sevColor(sev)

              return (
                <TableRow
                  key={a.id}
                  onClick={() => onSelectAlert(a)}
                  style={{
                    cursor: 'pointer',
                    borderColor: 'var(--border-sub)',
                    background: isSelected ? 'var(--accent-dim)' : 'transparent',
                  }}
                  onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLTableRowElement).style.background = 'var(--bg-hover)' }}
                  onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLTableRowElement).style.background = 'transparent' }}
                >
                  <TableCell style={{ padding: '7px 8px' }}>
                    <span style={{ display: 'block', width: '7px', height: '7px', borderRadius: '50%', background: color }} />
                  </TableCell>
                  <TableCell style={{ padding: '7px 6px', fontSize: '12px', fontWeight: 500, color: 'var(--text-pri)' }}>
                    {actLabel}
                  </TableCell>
                  <TableCell style={{ padding: '7px 6px', fontSize: '11px', fontFamily: 'var(--font-mono)', textAlign: 'right', color: 'var(--text-sec)' }}>
                    {area}
                  </TableCell>
                  <TableCell style={{ padding: '7px 6px', fontSize: '11px', color: 'var(--text-muted)' }}>
                    {a.detection_date?.slice(5) || '—'}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

export const Sidebar = memo(SidebarInner)
