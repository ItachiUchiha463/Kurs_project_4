import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { MetricChart } from '@/components/MetricChart'
import { CommandBlock, PageHead } from '@/components/small'
import { IncidentStatusBadge, StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { ago, duration } from '@/lib/format'
import { metricLabel } from '@/lib/metrics'
import { useChildren, useIncidents, useTarget, type Range } from '@/lib/queries'
import { agentConfig } from '@/pages/AddServer'

export function TargetPage() {
  const id = Number(useParams().id)
  const t = useTarget(id)
  const incidents = useIncidents({ target_id: id })
  const children = useChildren(id, t.data?.type === 'server')
  const [range, setRange] = useState<Range>('1h')
  const [tab, setTab] = useState<'charts' | 'incidents'>('charts')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [newToken, setNewToken] = useState<string | null>(null)
  const navigate = useNavigate()
  const qc = useQueryClient()

  if (t.isError) return <PageHead title="Об’єкт не знайдено" subtitle={<Link to="/" className="text-primary hover:underline">← На дашборд</Link>} />
  if (t.isPending) return <Skeleton className="h-64 w-full" />
  const target = t.data
  document.title = `${target.name} – Vigil`

  const disks = Object.keys(target.latest).filter((k) => k.startsWith('disk_usage:')).map((k) => k.slice('disk_usage:'.length))
  const clockDrift = target.clock_offset_s != null && Math.abs(target.clock_offset_s) > 60

  const remove = async () => {
    await api(`/targets/${id}`, { method: 'DELETE' })
    qc.invalidateQueries({ queryKey: ['targets'] })
    toast.success(`Об’єкт «${target.name}» видалено`)
    navigate('/')
  }
  const hide = async () => {
    await api(`/targets/${id}/hidden`, { method: 'PUT', body: { hidden: true } })
    qc.invalidateQueries({ queryKey: ['targets'] })
    qc.invalidateQueries({ queryKey: ['children', target.host_id] })
    toast.success(`Контейнер «${target.name}» сховано`)
    navigate(target.host_id ? `/targets/${target.host_id}` : '/')
  }
  const rotate = async () => setNewToken((await api<{ agent_token: string }>(`/targets/${id}/agent-token`, { method: 'POST' })).agent_token)

  return (
    <>
      <Link to="/" className="text-sm font-medium text-primary hover:underline">← Дашборд</Link>
      <PageHead title={target.name}
        subtitle={<>{target.type === 'server' ? 'Сервер' : target.type === 'container' ? `Контейнер · ${target.address}` : `Сервіс · ${target.address}`} · дані: {ago(target.last_seen)}{target.agent_version && ` · агент ${target.agent_version}`}</>}
        actions={<>
          <StatusBadge status={target.status} />
          {target.type === 'server' && <Button variant="outline" size="sm" onClick={rotate}>Новий токен агента</Button>}
          {target.source === 'discovered'
            ? <Button variant="outline" size="sm" onClick={hide}>Сховати</Button>
            : <Button variant="outline" size="sm" onClick={() => setConfirmDelete(true)}>Видалити</Button>}
        </>} />

      {clockDrift && (
        <p role="status" className="rounded-lg bg-warn-bg p-3 text-sm text-warn">
          Годинник сервера розходиться з сервісом на {Math.round(Math.abs(target.clock_offset_s!))} с – увімкніть синхронізацію часу. Мітки часу вже виправлено.
        </p>
      )}

      <div role="tablist" aria-label="Розділи" className="flex gap-1 border-b">
        {([['charts', 'Графіки'], ['incidents', `Інциденти${incidents.data?.length ? ` (${incidents.data.length})` : ''}`]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`min-h-11 border-b-2 px-4 text-sm font-medium ${tab === k ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}>{l}</button>
        ))}
      </div>

      {tab === 'charts' && (children.data ?? []).length > 0 && (
        <section aria-label="Контейнери" className="overflow-hidden rounded-xl border bg-card shadow-sm">
          <h2 className="border-b p-4 font-semibold">Контейнери ({children.data!.filter((c) => !c.hidden).length})</h2>
          <ul>
            {children.data!.filter((c) => !c.hidden).map((c) => (
              <li key={c.id} className="border-b last:border-b-0">
                <Link to={`/targets/${c.id}`} className="flex flex-wrap items-center gap-3 p-4 hover:bg-muted">
                  <StatusBadge status={c.status} />
                  <span className="font-medium">{c.name}</span>
                  <span className="text-sm text-muted-foreground">{c.address}</span>
                  <span className="num ml-auto text-sm text-muted-foreground">
                    {'container_cpu' in c.latest && `CPU ${Math.round(c.latest.container_cpu)} %`}
                    {'container_mem' in c.latest && ` · RAM ${Math.round(c.latest.container_mem)} %`}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {tab === 'charts' ? (
        <>
          <div className="flex gap-2" role="group" aria-label="Період">
            {([['1h', '1 год'], ['24h', '24 год']] as const).map(([k, l]) => (
              <Button key={k} size="sm" variant={range === k ? 'default' : 'outline'} aria-pressed={range === k} onClick={() => setRange(k)}>{l}</Button>
            ))}
          </div>
          {target.status === 'unknown' ? (
            <p className="rounded-xl border border-dashed p-8 text-center text-muted-foreground">Даних ще немає – графіки з’являться після першого пакета від агента.</p>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {target.type === 'server' ? (
                <>
                  <MetricChart targetId={id} metric="cpu_usage" range={range} />
                  <MetricChart targetId={id} metric="ram_usage" range={range} />
                  {disks.map((d) => <MetricChart key={d} targetId={id} metric="disk_usage" instance={d} range={range} title={`Заповненість диска ${d}`} />)}
                  <MetricChart targetId={id} metric="net_total" range={range} />
                  {'load_per_core' in target.latest && <MetricChart targetId={id} metric="load_per_core" range={range} />}
                  {target.ping_enabled && <MetricChart targetId={id} metric="ping_ms" range={range} />}
                </>
              ) : target.type === 'container' ? (
                <>
                  <MetricChart targetId={id} metric="container_cpu" range={range} />
                  <MetricChart targetId={id} metric="container_mem" range={range} />
                </>
              ) : (
                <>
                  <MetricChart targetId={id} metric="response_ms" range={range} />
                  {target.check_type === 'ping' && <MetricChart targetId={id} metric="packet_loss" range={range} />}
                </>
              )}
            </div>
          )}
        </>
      ) : (
        <section className="overflow-hidden rounded-xl border bg-card shadow-sm" aria-label="Інциденти об’єкта">
          {(incidents.data ?? []).length === 0 ? <p className="p-4 text-sm text-muted-foreground">Інцидентів не було.</p> : (
            <ul>{incidents.data!.map((i) => (
              <li key={i.id} className="border-b last:border-b-0">
                <Link to={`/incidents/${i.id}`} className="flex flex-wrap items-center gap-3 p-4 hover:bg-muted">
                  <IncidentStatusBadge status={i.status} severity={i.severity} />
                  <span>{metricLabel(i.metric, i.instance)}</span>
                  <span className="num ml-auto text-sm text-muted-foreground">{duration(i.started_at, i.resolved_at)}</span>
                </Link>
              </li>))}
            </ul>
          )}
        </section>
      )}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Видалити «{target.name}»?</DialogTitle>
            <DialogDescription>{target.type === 'server' ? 'Разом із сервером видаляться його метрики та інциденти; пов’язані сервіси залишаться, але втратять прив’язку. ' : 'Разом з об’єктом видаляться його метрики та інциденти. '}Це не можна скасувати.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>Скасувати</Button>
            <Button variant="destructive" onClick={remove}>Видалити</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!newToken} onOpenChange={(o) => !o && setNewToken(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новий токен агента</DialogTitle>
            <DialogDescription>Токен показується лише зараз. Старий уже не діє: оновіть agent.toml і перезапустіть агента.</DialogDescription>
          </DialogHeader>
          {newToken && <CommandBlock>{agentConfig(target.name, newToken)}</CommandBlock>}
          <DialogFooter><Button onClick={() => setNewToken(null)}>Готово</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
