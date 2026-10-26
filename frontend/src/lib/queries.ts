import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { getToken } from '@/lib/auth'
import type { Incident, IncidentDetail, Me, Point, Target } from '@/lib/types'

export type Range = '1h' | '24h' | '7d' | '30d'
export const RANGE_MINUTES: Record<Range, number> = { '1h': 60, '24h': 1440, '7d': 10_080, '30d': 43_200 }

export const useMe = () =>
  useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me'), enabled: !!getToken(), staleTime: 60_000 })

export const useTargets = () => useQuery({ queryKey: ['targets'], queryFn: () => api<Target[]>('/targets') })

export const useTarget = (id: number) =>
  useQuery({ queryKey: ['target', id], queryFn: () => api<Target>(`/targets/${id}`) })

export const useChildren = (id: number, enabled: boolean) =>
  useQuery({ queryKey: ['children', id], queryFn: () => api<Target[]>(`/targets/${id}/children`), enabled })

export interface IncidentFilters {
  status?: 'active' | 'resolved'
  severity?: 'warning' | 'critical'
  target_id?: number
}

export const useIncidents = (filters: IncidentFilters = {}) =>
  useQuery({ queryKey: ['incidents', filters], queryFn: () => api<Incident[]>('/incidents', { params: { ...filters, limit: 100 } }) })

export const useIncident = (id: number) =>
  useQuery({ queryKey: ['incident', id], queryFn: () => api<IncidentDetail>(`/incidents/${id}`) })

/** Ряд для графіка; ключ 1h доповнюється подіями WebSocket (див. ws/live.ts), решта оновлюється раз на хвилину. */
export const useSeries = (targetId: number, name: string, instance: string, range: Range) =>
  useQuery({
    queryKey: ['series', targetId, name, instance, range],
    queryFn: () => {
      const end = new Date()
      const start = new Date(end.getTime() - RANGE_MINUTES[range] * 60_000)
      return api<Point[]>(`/targets/${targetId}/metrics`, {
        params: { name, instance, from: start.toISOString(), to: end.toISOString() },
      })
    },
    refetchInterval: range === '1h' ? 120_000 : range === '24h' ? 60_000 : 300_000,  // довгі періоди беруться з агрегату по 5 хв
  })
