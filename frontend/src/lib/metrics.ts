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
  db_up: { label: 'База даних доступна', unit: '' },
  db_response_ms: { label: 'Час відповіді БД', unit: 'мс' },
  db_connections: { label: 'З’єднання з БД', unit: '' },
  db_connections_pct: { label: 'З’єднання, % від максимуму', unit: '%', warn: 80, crit: 95, max: 100 },
  db_idle_in_tx: { label: 'Транзакції idle in transaction', unit: '', warn: 5, crit: 20 },
  db_longest_query_s: { label: 'Найдовший запит', unit: 'с', warn: 30, crit: 300 },
  db_tps: { label: 'Транзакцій за секунду', unit: '' },
  db_cache_hit_pct: { label: 'Влучання в кеш', unit: '%', max: 100 },
  db_locks_waiting: { label: 'Запити, що чекають блокування', unit: '' },
  db_size_mb: { label: 'Розмір БД', unit: 'МБ' },
  ping_ms: { label: 'Час відповіді на ping', unit: 'мс', warn: 1000, crit: 3000 },
  packet_loss: { label: 'Втрати пакетів', unit: '%', warn: 10, crit: 50, max: 100 },
}

/** Метрики 0/1 (доступність, прапорці): їхнє значення в тексті не показуємо; дзеркало FLAG_TEXT бекенда (notify/messages.py). */
export const FLAG_METRICS = new Set([
  'available', 'agent_alive', 'ping_available', 'container_running', 'db_up', 'container_oom_killed', 'container_health',
])

/** Підписи, спільні для звітів, порогів і правил. */
export const TYPE_LABEL: Record<string, string> = { server: 'Сервер', service: 'Сервіс', container: 'Контейнер', database: 'База даних' }
export const AGG_LABEL: Record<string, string> = { last: 'останнє значення', avg: 'середнє', max: 'максимум', min: 'мінімум', delta: 'приріст' }

export const metricLabel = (metric: string, instance = '') =>
  (METRICS[metric]?.label ?? metric) + (instance ? ` (${instance})` : '')

export const metricUnit = (metric: string) => METRICS[metric]?.unit ?? ''

export const SEVERITY_LABEL: Record<Severity, string> = { warning: 'Попередження', critical: 'Критичний' }
