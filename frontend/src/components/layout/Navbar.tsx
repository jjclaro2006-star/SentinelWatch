import { FC, memo } from 'react'
import { ViewMode } from '../../types'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

interface NavbarProps {
  total: number
  mode: ViewMode
  lastSync: Date | null
  onToggleSidebar: () => void
  onModeChange: (mode: string) => void
}

const NavbarInner: FC<NavbarProps> = ({ total, mode, lastSync, onToggleSidebar, onModeChange }) => {
  const syncLabel = lastSync
    ? `Actualizado ${Math.floor((Date.now() - lastSync.getTime()) / 60000)} min atrás`
    : 'Sincronizando...'

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: 'var(--nav-h)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '0 14px',
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <button
        onClick={onToggleSidebar}
        style={{
          width: '28px',
          height: '28px',
          flex: 'none',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: '4px',
          padding: '6px',
          background: 'transparent',
          border: '1px solid var(--border)',
          cursor: 'pointer',
          borderRadius: '4px',
          transition: 'border-color .15s',
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--text-sec)' }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border)' }}
        aria-label="Toggle sidebar"
      >
        <span style={{ display: 'block', height: '1.5px', background: 'var(--text-sec)', borderRadius: '1px' }} />
        <span style={{ display: 'block', height: '1.5px', background: 'var(--text-sec)', borderRadius: '1px' }} />
        <span style={{ display: 'block', height: '1.5px', background: 'var(--text-sec)', borderRadius: '1px' }} />
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 'none' }}>
        <svg width="16" height="18" viewBox="0 0 18 20" style={{ display: 'block', flexShrink: 0 }}>
          <polygon points="9,1 17,5.5 17,14.5 9,19 1,14.5 1,5.5" fill="none" stroke="var(--accent)" strokeWidth="1.3" />
          <circle cx="9" cy="10" r="2.4" fill="var(--accent)" />
        </svg>
        <span style={{ fontWeight: 600, fontSize: '14px', letterSpacing: '.01em', color: 'var(--text-pri)' }}>
          SentinelWatch
        </span>
      </div>

      <div style={{ width: '1px', height: '20px', background: 'var(--border)', flex: 'none' }} />

      <Badge
        variant="outline"
        className="font-mono text-xs px-2 h-6"
        style={{ color: 'var(--text-pri)', borderColor: 'var(--border)', background: 'var(--bg-elevated)' }}
      >
        {total} alertas
      </Badge>

      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', cursor: 'default', userSelect: 'none' }}>
              {syncLabel}
            </span>
          </TooltipTrigger>
          <TooltipContent
            side="bottom"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-sec)', fontSize: '11px' }}
          >
            Polling cada 30 segundos
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <div style={{ flex: 1 }} />

      <Tabs value={mode} onValueChange={onModeChange}>
        <TabsList
          style={{
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            height: '30px',
            gap: '1px',
            padding: '2px',
          }}
        >
          {[
            { value: 'globe', label: 'Globo' },
            { value: 'map', label: 'Mapa' },
            { value: 'satellite', label: 'Satélite' },
            { value: 'list', label: 'Lista' },
          ].map(({ value, label }) => (
            <TabsTrigger
              key={value}
              value={value}
              style={{ fontSize: '12px', height: '26px', padding: '0 11px' }}
            >
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    </div>
  )
}

export const Navbar = memo(NavbarInner)
