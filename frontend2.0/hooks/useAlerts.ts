import { useState, useEffect, useCallback } from 'react'
import type { Alert, AlertSummary } from '@/lib/sentinel-data'
import { fetchAlerts, fetchSummary } from '@/lib/api'


export interface UseAlertsReturn {
  alerts: Alert[]
  summary: AlertSummary | null
  error: string | null
  loading: boolean
  lastSync: Date | null
}

const POLL_INTERVAL = 30_000

export function useAlerts(): UseAlertsReturn {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [summary, setSummary] = useState<AlertSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastSync, setLastSync] = useState<Date | null>(null)

  const poll = useCallback(async () => {
    try {
      const [alertsData, summaryData] = await Promise.all([fetchAlerts(), fetchSummary()])
      setAlerts(alertsData)
      setSummary(summaryData)
      setError(null)
      setLastSync(new Date())
    } catch {
      setError('API no disponible')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    poll()
  }, [poll])

  useEffect(() => {
    const id = setInterval(poll, POLL_INTERVAL)
    return () => clearInterval(id)
  }, [poll])

  useEffect(() => {
    if (!error) return
    const id = setTimeout(() => setError(null), 4000)
    return () => clearTimeout(id)
  }, [error])

  return { alerts, summary, error, loading, lastSync }
}
