import { useState, useEffect, useCallback } from 'react'
import { AlertProperties, AlertSummary } from '../types'
import { fetchAlerts, fetchSummary } from '../api'

interface UseAlertsReturn {
  alerts: AlertProperties[]
  summary: AlertSummary | null
  error: string | null
  loading: boolean
  lastSync: Date | null
}

const POLL_INTERVAL = 30 * 1000 // 30 seconds

export function useAlerts(): UseAlertsReturn {
  const [alerts, setAlerts] = useState<AlertProperties[]>([])
  const [summary, setSummary] = useState<AlertSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastSync, setLastSync] = useState<Date | null>(null)

  const poll = useCallback(async () => {
    try {
      const [alertsData, summaryData] = await Promise.all([fetchAlerts(), fetchSummary()])
      const alertsList = alertsData.features?.map((f) => f.properties) || []
      setAlerts(alertsList)
      setSummary(summaryData)
      setError(null)
      setLastSync(new Date())
    } catch (err) {
      setError('API no disponible — reintentando')
      console.error('Poll error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial fetch
  useEffect(() => {
    poll()
  }, [poll])

  // Polling interval
  useEffect(() => {
    const pollInterval = setInterval(() => {
      poll()
    }, POLL_INTERVAL)

    return () => clearInterval(pollInterval)
  }, [poll])

  // Clear error after 2.6 seconds
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 2600)
      return () => clearTimeout(timer)
    }
  }, [error])

  return { alerts, summary, error, loading, lastSync }
}
