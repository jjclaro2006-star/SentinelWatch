import { useReducer, useCallback, useMemo, useEffect } from 'react'
import { AppState, AlertProperties, ViewMode, Activity, Severity } from './types'
import { normSev, sevRank } from './utils'
import { useAlerts } from './hooks/useAlerts'
import { CesiumGlobe } from './components/globe/CesiumGlobe'
import { Navbar } from './components/layout/Navbar'
import { Sidebar } from './components/layout/Sidebar'
import { DetailPanel } from './components/layout/DetailPanel'
import { ListView } from './components/layout/ListView'

type Action =
  | { type: 'SET_MODE'; payload: ViewMode }
  | { type: 'SET_ALERTS'; payload: AlertProperties[] }
  | { type: 'SET_SELECTED'; payload: AlertProperties | null }
  | { type: 'TOGGLE_ACTIVITY'; payload: Activity | 'all' }
  | { type: 'TOGGLE_SEVERITY'; payload: Severity | 'all' }
  | { type: 'SET_VERDICT'; payload: 'all' | 'ILEGAL' | 'Requiere' }
  | { type: 'TOGGLE_SIDEBAR' }
  | { type: 'SET_ERROR'; payload: string | null }

function appReducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'SET_MODE':
      return { ...state, mode: action.payload }
    case 'SET_ALERTS':
      return { ...state, alerts: action.payload }
    case 'SET_SELECTED':
      return { ...state, selected: action.payload }
    case 'TOGGLE_ACTIVITY': {
      const newFilterAct = new Set(state.filterAct)
      if (action.payload === 'all') {
        return { ...state, filterAct: new Set(['all']) }
      }
      newFilterAct.delete('all')
      if (newFilterAct.has(action.payload)) {
        newFilterAct.delete(action.payload)
      } else {
        newFilterAct.add(action.payload)
      }
      if (newFilterAct.size === 0) newFilterAct.add('all')
      return { ...state, filterAct: newFilterAct }
    }
    case 'TOGGLE_SEVERITY': {
      const newFilterSev = new Set(state.filterSev)
      if (action.payload === 'all') {
        return { ...state, filterSev: new Set(['all']) }
      }
      newFilterSev.delete('all')
      if (newFilterSev.has(action.payload)) {
        newFilterSev.delete(action.payload)
      } else {
        newFilterSev.add(action.payload)
      }
      if (newFilterSev.size === 0) newFilterSev.add('all')
      return { ...state, filterSev: newFilterSev }
    }
    case 'SET_VERDICT':
      return { ...state, filterVer: action.payload }
    case 'TOGGLE_SIDEBAR':
      return { ...state, sidebarOpen: !state.sidebarOpen }
    case 'SET_ERROR':
      return { ...state, error: action.payload }
    default:
      return state
  }
}

const initialState: AppState = {
  mode: 'map',
  alerts: [],
  filtered: [],
  selected: null,
  filterAct: new Set(['all']),
  filterSev: new Set(['all']),
  filterVer: 'all',
  sidebarOpen: true,
  summary: null,
  error: null,
}

export default function App() {
  const [state, dispatch] = useReducer(appReducer, initialState)
  const { alerts, error, lastSync } = useAlerts()

  useEffect(() => {
    dispatch({ type: 'SET_ALERTS', payload: alerts })
  }, [alerts])

  useEffect(() => {
    dispatch({ type: 'SET_ERROR', payload: error })
  }, [error])

  const filtered = useMemo(() => {
    return state.alerts.filter((a) => {
      const sev = normSev(a.severity)
      const okA = state.filterAct.has('all') || state.filterAct.has(a.actividad as Activity)
      const okS = state.filterSev.has('all') || state.filterSev.has(sev)
      let okV = true
      if (state.filterVer === 'ILEGAL') okV = a.veredicto === 'ILEGAL'
      else if (state.filterVer === 'Requiere') okV = (a.veredicto || '').startsWith('Requiere')
      return okA && okS && okV
    })
  }, [state.alerts, state.filterAct, state.filterSev, state.filterVer])

  const handleSelectAlert = useCallback((alert: AlertProperties) => {
    dispatch({ type: 'SET_SELECTED', payload: alert })
  }, [])

  const handleDeselectAlert = useCallback(() => {
    dispatch({ type: 'SET_SELECTED', payload: null })
  }, [])

  const handleModeChange = useCallback((mode: ViewMode) => {
    dispatch({ type: 'SET_MODE', payload: mode })
  }, [])

  const handleToggleSidebar = useCallback(() => {
    dispatch({ type: 'TOGGLE_SIDEBAR' })
  }, [])

  const handleToggleAct = useCallback((key: Activity | 'all') => {
    dispatch({ type: 'TOGGLE_ACTIVITY', payload: key })
  }, [])

  const handleToggleSev = useCallback((key: Severity | 'all') => {
    dispatch({ type: 'TOGGLE_SEVERITY', payload: key })
  }, [])

  const handleChangeVer = useCallback((val: string) => {
    dispatch({ type: 'SET_VERDICT', payload: val as 'all' | 'ILEGAL' | 'Requiere' })
  }, [])

  const isListMode = state.mode === 'list'

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'var(--bg-base)', fontFamily: 'var(--font-sans)', overflow: 'hidden' }}>
      {!isListMode && (
        <CesiumGlobe
          alerts={filtered}
          selected={state.selected}
          mode={state.mode}
          onSelectAlert={handleSelectAlert}
          onModeChange={handleModeChange}
        />
      )}

      {state.error && (
        <div
          style={{
            position: 'fixed',
            left: '50%',
            bottom: '56px',
            transform: 'translateX(-50%)',
            zIndex: 200,
            background: 'rgba(248,81,73,.1)',
            border: '1px solid rgba(248,81,73,.35)',
            color: 'var(--sev-alta)',
            fontSize: '12px',
            padding: '9px 18px',
            borderRadius: '4px',
          }}
        >
          ⚠ {state.error}
        </div>
      )}

      <Navbar
        total={filtered.length}
        mode={state.mode}
        lastSync={lastSync}
        onToggleSidebar={handleToggleSidebar}
        onModeChange={(m) => handleModeChange(m as ViewMode)}
      />

      {isListMode ? (
        <ListView
          alerts={filtered}
          onSelectAlert={handleSelectAlert}
          filterAct={state.filterAct}
          filterSev={state.filterSev}
          filterVer={state.filterVer}
          onToggleAct={handleToggleAct}
          onToggleSev={handleToggleSev}
          onChangeVer={handleChangeVer}
        />
      ) : (
        <>
          <Sidebar
            isOpen={state.sidebarOpen}
            alerts={state.alerts}
            filtered={filtered}
            selected={state.selected}
            filterAct={state.filterAct}
            filterSev={state.filterSev}
            filterVer={state.filterVer}
            onToggleAct={handleToggleAct}
            onToggleSev={handleToggleSev}
            onChangeVer={handleChangeVer}
            onSelectAlert={handleSelectAlert}
          />
          <DetailPanel alert={state.selected} onClose={handleDeselectAlert} />
        </>
      )}
    </div>
  )
}
