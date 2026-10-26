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
  ping_available: { label: 'Ping сервера', unit: '' },
  container_running: { label: 'Контейнер працює', unit: '' },
  container_cpu: { label: 'CPU контейнера', unit: '%', warn: 80, crit: 95, max: 100 },
  container_mem: { label: 'RAM контейнера', unit: '%', warn: 85, crit: 95, max: 100 },
  container_mem_bytes: { label: 'RAM контейнера', unit: 'МБ' },
  container_restarts: { label: 'Перезапуски контейнера', unit: '' },
  container_health: { label: 'Healthcheck контейнера', unit: '' },
  container_oom_killed: { label: 'Контейнер убито через пам’ять', unit: '' },
  container_exit_code: { label: 'Код виходу контейнера', unit: '' },
  ping_ms: { label: 'Час відповіді на ping', unit: 'мс', warn: 1000, crit: 3000 },
  packet_loss: { label: 'Втрати пакетів', unit: '%', warn: 10, crit: 50, max: 100 },
}

export const metricLabel = (metric: string, instance = '') =>
  (METRICS[metric]?.label ?? metric) + (instance ? ` (${instance})` : '')

export const metricUnit = (metric: string) => METRICS[metric]?.unit ?? ''

export const SEVERITY_LABEL: Record<Severity, string> = { warning: 'Попередження', critical: 'Критичний' }
