import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'
import { toast } from 'sonner'

import { getToken } from '@/lib/auth'
import { metricLabel } from '@/lib/metrics'
import type { Incident, LiveEvent, Point, Target } from '@/lib/types'

export type LiveStatus = 'connecting' | 'live' | 'reconnecting'
const MAX_POINTS_1H = 400
let status: LiveStatus = 'connecting'
const listeners = new Set<() => void>()
const setStatus = (s: LiveStatus) => {
  status = s
  listeners.forEach((l) => l())
}

export const useLiveStatus = () =>
  useSyncExternalStore((cb) => (listeners.add(cb), () => listeners.delete(cb)), () => status)

function applyMetrics(qc: QueryClient, e: Extract<LiveEvent, { type: 'metrics' }>) {
  const patch = (t: Target): Target =>
    t.id === e.target_id ? { ...t, status: e.status, last_seen: e.last_seen, latest: { ...t.latest, ...e.values } } : t
  qc.setQueryData<Target[]>(['targets'], (old) => old?.map(patch))
  qc.setQueryData<Target>(['target', e.target_id], (old) => old && patch(old))
  const now = new Date().toISOString()
  for (const [key, value] of Object.entries(e.values)) {
    const [name, instance = ''] = key.split(/:(.*)/s)  // «disk_usage:/» → ["disk_usage", "/"]
    qc.setQueryData<Point[]>(['series', e.target_id, name, instance, '1h'], (old) =>
      old ? [...old, { ts: now, value }].slice(-MAX_POINTS_1H) : old)
  }
}

function applyIncident(qc: QueryClient, change: string, inc: Incident) {
  qc.invalidateQueries({ queryKey: ['incidents'] })
  qc.invalidateQueries({ queryKey: ['incident', inc.id] })
  if (change === 'opened' || change === 'escalated') {
    const text = `${inc.target_name}: ${metricLabel(inc.metric, inc.instance)}`
    const show = inc.severity === 'critical' ? toast.error : toast.warning
    show(inc.severity === 'critical' ? `Критично · ${text}` : `Попередження · ${text}`, {
      action: { label: 'Відкрити', onClick: () => window.location.assign(`/incidents/${inc.id}`) },
      duration: 8000,
    })
  } else if (change === 'resolved') {
    toast.success(`Відновлено · ${inc.target_name}`)
  }
}

/** Одне WS-з'єднання на застосунок: події оновлюють кеш TanStack Query, перепідключення 1, 2, 4 … 30 с (ТЗ 10.1). */
export function useLive() {
  const qc = useQueryClient()
  useEffect(() => {
    let ws: WebSocket | null = null
    let stopped = false
    let delay = 1000
    let timer: number | undefined

    const connect = () => {
      const token = getToken()
      if (!token || stopped) return
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`)
      ws.onopen = () => ws?.send(JSON.stringify({ type: 'auth', token }))  // токен не в URL
      ws.onmessage = (m) => {
        const e = JSON.parse(m.data) as LiveEvent
        if (e.type === 'ready') {
          delay = 1000
          setStatus('live')
          // дані могли змінитися, поки з'єднання не було
          qc.invalidateQueries({ queryKey: ['targets'] })
          qc.invalidateQueries({ queryKey: ['incidents'] })
        } else if (e.type === 'metrics') applyMetrics(qc, e)
        else if (e.type === 'incident') applyIncident(qc, e.change, e.incident)
      }
      ws.onclose = () => {
        if (stopped) return
        setStatus('reconnecting')
        timer = window.setTimeout(connect, delay)
        delay = Math.min(delay * 2, 30_000)
      }
    }
    connect()
    return () => {
      stopped = true
      window.clearTimeout(timer)
      ws?.close()
      setStatus('connecting')
    }
  }, [qc])
}
