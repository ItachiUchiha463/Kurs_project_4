import { useState } from 'react'
import { Link } from 'react-router-dom'

import { EmptyState, LinkButton, PageHead } from '@/components/small'
import { IncidentStatusBadge, StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ago, duration, num, plural } from '@/lib/format'
import { METRICS, metricLabel } from '@/lib/metrics'
import { useIncidents, useTargets } from '@/lib/queries'
import type { Status, Target } from '@/lib/types'
import { cn } from '@/lib/utils'

const ORDER: Record<Status, number> = { critical: 0, unavailable: 1, warning: 2, unknown: 3, ok: 4 }

function tone(metric: string, value: number): string {
  const m = METRICS[metric]
  if (m?.crit != null && value > m.crit) return 'text-crit'
  if (m?.warn != null && value > m.warn) return 'text-warn'
  return ''
}

function Metric({ label, value, metric }: { label: string; value: number | undefined; metric: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn('num text-base', value != null && tone(metric, value))}>
        {value == null ? '–' : `${num(value)}${METRICS[metric]?.unit ? ' ' + METRICS[metric].unit : ''}`}
      </div>
    </div>
  )
}

function TargetCard({ t }: { t: Target }) {
  const disks = Object.entries(t.latest).filter(([k]) => k.startsWith('disk_usage:')).map(([, v]) => v)
  return (
    <Link to={`/targets/${t.id}`} className={cn('flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-sm transition hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring',
      t.status === 'critical' && 'border-crit/50', t.status === 'warning' && 'border-warn/50')}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{t.name}</h3>
          <p className="truncate text-xs text-muted-foreground">{t.type === 'server' ? 'Сервер' : `Сервіс · ${t.address}`}</p>
        </div>
        <StatusBadge status={t.status} />
      </div>
      {t.status === 'unknown' ? (
        <p className="text-sm text-muted-foreground">{t.type === 'server' ? 'Очікуємо перші дані від агента…' : 'Перша перевірка ще не виконана'}</p>
      ) : t.type === 'server' ? (
        <div className="grid grid-cols-3 gap-2">
          <Metric label="CPU" metric="cpu_usage" value={t.latest.cpu_usage} />
          <Metric label="RAM" metric="ram_usage" value={t.latest.ram_usage} />
          <Metric label="Диск" metric="disk_usage" value={disks.length ? Math.max(...disks) : undefined} />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <Metric label="Відповідь" metric="response_ms" value={t.latest.response_ms} />
          <Metric label="HTTP" metric="status_code" value={t.latest.status_code} />
        </div>
      )}
      <p className="text-xs text-muted-foreground">Дані: {ago(t.last_seen)}</p>
    </Link>
  )
}

export function DashboardPage() {
  document.title = 'Дашборд – Vigil'
  const targets = useTargets()
  const incidents = useIncidents({ status: 'active' })
  const [filter, setFilter] = useState<'all' | 'server' | 'service'>('all')

  if (targets.isPending) return <><PageHead title="Дашборд" /><Skeleton className="h-64 w-full" /></>
  const all = targets.data ?? []
  if (all.length === 0) {
    return (
      <>
        <PageHead title="Дашборд" />
        <EmptyState title="Підключіть перший сервер" action={<LinkButton to="/targets/new">Додати сервер</LinkButton>}>
          Vigil збирає метрики з вашого сервера, виявляє проблеми й пояснює їхню причину.
        </EmptyState>
      </>
    )
  }

  const active = incidents.data ?? []
  const critical = active.filter((i) => i.severity === 'critical' && i.status === 'open')
  const stats = {
    ok: all.filter((t) => t.status === 'ok').length,
    problem: all.filter((t) => t.status === 'warning' || t.status === 'critical').length,
    off: all.filter((t) => t.status === 'unavailable').length,
  }
  const visible = all.filter((t) => filter === 'all' || t.type === filter).sort((a, b) => ORDER[a.status] - ORDER[b.status])
  const needAttention = stats.problem + stats.off

  return (
    <>
      <PageHead title="Дашборд" subtitle={`${all.length} ${plural(all.length, 'об’єкт', 'об’єкти', 'об’єктів')}`}
        actions={<LinkButton to="/targets/new">+ Додати сервер</LinkButton>} />

      <p className="text-lg" aria-live="polite">
        {needAttention === 0
          ? <><b>Усе працює.</b> <span className="text-muted-foreground">Активних проблем немає.</span></>
          : <><b>{needAttention} {plural(needAttention, 'об’єкт потребує', 'об’єкти потребують', 'об’єктів потребують')} уваги</b>
            {critical.length > 0 && <span className="text-muted-foreground">: {critical.slice(0, 2).map((i) => i.target_name).join(', ')}</span>}</>}
      </p>

      <section aria-label="Активні інциденти" className="overflow-hidden rounded-xl border bg-card shadow-sm">
        <div className="flex items-center justify-between border-b p-4">
          <h2 className="font-semibold">Активні інциденти <span className="text-muted-foreground">{active.length}</span></h2>
          <Link to="/incidents" className="text-sm font-medium text-primary hover:underline">Усі інциденти →</Link>
        </div>
        {active.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">Усе добре: відкритих інцидентів немає.</p>
        ) : (
          <ul>
            {active.slice(0, 5).map((i) => (
              <li key={i.id} className="border-b last:border-b-0">
                <Link to={`/incidents/${i.id}`} className="flex flex-wrap items-center gap-3 p-4 hover:bg-muted">
                  <IncidentStatusBadge status={i.status} severity={i.severity} />
                  <span className="font-semibold">{i.target_name}</span>
                  <span className="text-muted-foreground">{metricLabel(i.metric, i.instance)}</span>
                  <span className="num ml-auto text-sm text-muted-foreground">{duration(i.started_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Підсумок" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[['Об’єктів', all.length, ''], ['Працюють', stats.ok, 'text-ok'], ['З проблемами', stats.problem, stats.problem ? 'text-warn' : ''], ['Недоступні', stats.off, stats.off ? 'text-off' : '']].map(([l, v, c]) => (
          <div key={String(l)} className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">{l}</div>
            <div className={cn('num text-3xl', c as string)}>{v}</div>
          </div>
        ))}
      </section>

      <section aria-label="Об’єкти" className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {([['all', 'Усі'], ['server', 'Сервери'], ['service', 'Сервіси']] as const).map(([k, l]) => (
            <Button key={k} size="sm" variant={filter === k ? 'default' : 'outline'} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</Button>
          ))}
          <span className="ml-auto text-sm text-muted-foreground">Спершу об’єкти з проблемами</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{visible.map((t) => <TargetCard key={t.id} t={t} />)}</div>
      </section>
    </>
  )
}
