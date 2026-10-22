import type { Severity } from '@/lib/types'

export interface MetricMeta {
  label: string
  unit: string
  /** пороги для ліній на графіку; дзеркало типових порогів бекенда (ТЗ 7.3), v1.3 – з API */
  warn?: number
  crit?: number
  max?: number
}

export const METRICS: Record<string, MetricMeta> = {
  cpu_usage: { label: 'Завантаження CPU', unit: '%', warn: 80, crit: 95, max: 100 },
  ram_usage: { label: 'Використання RAM', unit: '%', warn: 85, crit: 95, max: 100 },
  swap_usage: { label: 'Використання swap', unit: '%', max: 100 },
  disk_usage: { label: 'Заповненість диска', unit: '%', warn: 85, crit: 95, max: 100 },
  load_per_core: { label: 'Навантаження на ядро', unit: '', warn: 1.5, crit: 3 },
  net_in: { label: 'Мережа, вхідний трафік', unit: 'КБ/с' },
  net_out: { label: 'Мережа, вихідний трафік', unit: 'КБ/с' },
  net_total: { label: 'Мережа, весь трафік', unit: 'КБ/с' },
  process_count: { label: 'Процеси', unit: '' },
  response_ms: { label: 'Час відповіді', unit: 'мс', warn: 1000, crit: 3000 },
  available: { label: 'Доступність', unit: '' },
  agent_alive: { label: 'Агент надсилає дані', unit: '' },
  status_code: { label: 'Код відповіді HTTP', unit: '' },
}

export const metricLabel = (metric: string, instance = '') =>
  (METRICS[metric]?.label ?? metric) + (instance ? ` (${instance})` : '')

export const metricUnit = (metric: string) => METRICS[metric]?.unit ?? ''

export const SEVERITY_LABEL: Record<Severity, string> = { warning: 'Попередження', critical: 'Критичний' }
