import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { PageHead } from '@/components/small'
import { IncidentStatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { dateTime, duration } from '@/lib/format'
import { metricLabel } from '@/lib/metrics'
import { useIncidents, type IncidentFilters } from '@/lib/queries'

const TABS: [IncidentFilters['status'] | 'all', string][] = [['active', 'Активні'], ['resolved', 'Закриті'], ['all', 'Усі']]

export function IncidentsPage() {
  document.title = 'Інциденти – Vigil'
  const [tab, setTab] = useState<IncidentFilters['status'] | 'all'>('active')
  const [severity, setSeverity] = useState<IncidentFilters['severity']>()
  const q = useIncidents({ status: tab === 'all' ? undefined : tab, severity })
  const navigate = useNavigate()

  return (
    <>
      <PageHead title="Інциденти" />
      <div className="flex flex-wrap items-center gap-2">
        {TABS.map(([k, l]) => <Button key={k} size="sm" variant={tab === k ? 'default' : 'outline'} aria-pressed={tab === k} onClick={() => setTab(k)}>{l}</Button>)}
        <span className="mx-2 h-5 w-px bg-border" aria-hidden="true" />
        {([[undefined, 'Будь-який рівень'], ['critical', 'Критичні'], ['warning', 'Попередження']] as const).map(([k, l]) => (
          <Button key={l} size="sm" variant={severity === k ? 'secondary' : 'ghost'} aria-pressed={severity === k} onClick={() => setSeverity(k)}>{l}</Button>
        ))}
      </div>

      {q.isPending ? <Skeleton className="h-48 w-full" /> : (q.data ?? []).length === 0 ? (
        <p className="rounded-xl border border-dashed p-10 text-center text-muted-foreground">
          {tab === 'active' ? 'Активних інцидентів немає – усе працює.' : 'Інцидентів не знайдено.'}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card shadow-sm">
          <Table>
            <TableHeader>
              <TableRow><TableHead>Статус</TableHead><TableHead>Об’єкт</TableHead><TableHead>Метрика</TableHead><TableHead>Початок</TableHead><TableHead>Тривалість</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {q.data!.map((i) => (
                <TableRow key={i.id} className="cursor-pointer" onClick={() => navigate(`/incidents/${i.id}`)}>
                  <TableCell><IncidentStatusBadge status={i.status} severity={i.severity} /></TableCell>
                  <TableCell><Link to={`/incidents/${i.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>{i.target_name}</Link></TableCell>
                  <TableCell>{metricLabel(i.metric, i.instance)}</TableCell>
                  <TableCell className="num">{dateTime(i.started_at)}</TableCell>
                  <TableCell className="num">{duration(i.started_at, i.resolved_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  )
}
