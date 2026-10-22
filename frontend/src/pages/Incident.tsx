import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Minus } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import type { z } from 'zod'

import { applyApiError, Field } from '@/components/Field'
import { MetricChart } from '@/components/MetricChart'
import { PageHead } from '@/components/small'
import { IncidentStatusBadge, SeverityBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { resolveSchema } from '@/forms/schemas'
import { api } from '@/lib/api'
import { dateTime, duration, num, time } from '@/lib/format'
import { metricLabel, metricUnit } from '@/lib/metrics'
import { useIncident } from '@/lib/queries'
import type { IncidentEvent } from '@/lib/types'

const EVENT_TEXT: Record<string, string> = {
  detected: 'Виявлено відхилення',
  opened: 'Інцидент відкрито – порушення триває заданий час',
  escalated: 'Рівень підвищено до критичного',
  deescalated: 'Рівень знижено до попередження',
  acknowledged: 'Підтверджено: хтось уже займається',
  resolved: 'Інцидент закрито',
}
const DOT: Record<string, string> = { detected: 'bg-off', opened: 'bg-crit', escalated: 'bg-crit', deescalated: 'bg-warn', acknowledged: 'bg-ack', resolved: 'bg-ok' }

function eventText(e: IncidentEvent, metric: string): string {
  const base = EVENT_TEXT[e.type] ?? e.type
  const val = e.value != null && e.type !== 'acknowledged' && !['available', 'agent_alive'].includes(metric) ? `: ${num(e.value)} ${metricUnit(metric)}`.trimEnd() : ''
  return e.note ? `${e.note}` : base + (e.type === 'detected' || e.type === 'escalated' ? val : '')
}

export function IncidentPage() {
  const id = Number(useParams().id)
  const q = useIncident(id)
  const qc = useQueryClient()
  const [resolving, setResolving] = useState(false)
  const form = useForm<z.infer<typeof resolveSchema>>({ resolver: zodResolver(resolveSchema) })

  if (q.isError) return <PageHead title="Інцидент не знайдено" subtitle={<Link to="/incidents" className="text-primary hover:underline">← До списку</Link>} />
  if (q.isPending) return <Skeleton className="h-64 w-full" />
  const inc = q.data
  document.title = `INC-${inc.id} – Vigil`
  const live = inc.status === 'open' || inc.status === 'acknowledged'
  const refresh = () => { qc.invalidateQueries({ queryKey: ['incident', id] }); qc.invalidateQueries({ queryKey: ['incidents'] }) }

  const acknowledge = async () => {
    try { await api(`/incidents/${id}/acknowledge`, { method: 'POST' }); toast.success('Підтверджено: ви займаєтесь цим інцидентом'); refresh() }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не вдалося') }
  }
  const resolve = form.handleSubmit(async (v) => {
    try {
      await api(`/incidents/${id}/resolve`, { method: 'POST', body: v })
      setResolving(false); form.reset(); toast.success('Інцидент закрито'); refresh()
    } catch (e) {
      form.setError('root', { message: applyApiError(e, form.setError, ['comment']) ?? undefined })
    }
  })
  const d = inc.diagnosis

  return (
    <>
      <Link to="/incidents" className="text-sm font-medium text-primary hover:underline">← Інциденти</Link>
      <PageHead title={`${inc.target_name}: ${metricLabel(inc.metric, inc.instance)}`}
        subtitle={<>INC-{inc.id} · відкрито о {time(inc.started_at)}{inc.resolved_at ? ` · закрито о ${time(inc.resolved_at)}` : ''} · триває {duration(inc.started_at, inc.resolved_at)}</>}
        actions={<><SeverityBadge severity={inc.severity} />{inc.status !== 'open' && <IncidentStatusBadge status={inc.status} severity={inc.severity} />}</>} />

      {live && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={acknowledge} disabled={inc.status !== 'open'}>{inc.status === 'open' ? 'Підтвердити – я займаюся' : 'Підтверджено'}</Button>
          <Button variant="outline" onClick={() => setResolving(true)}>Закрити вручну</Button>
        </div>
      )}
      {inc.resolve_comment && <p className="rounded-lg bg-muted p-3 text-sm"><b>Коментар при закритті:</b> {inc.resolve_comment}</p>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid gap-4">
          <section aria-label="Діагностика" className="overflow-hidden rounded-xl border bg-card shadow-sm">
            <div className="border-b bg-accent p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-accent-foreground">Ймовірна причина</div>
              <h2 className="text-xl font-semibold">{d?.cause ?? 'Визначаємо причину…'}</h2>
            </div>
            {d && (
              <>
                <div className="flex gap-4 border-b p-4">
                  <div className="shrink-0 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Що зробити</div>
                  <p>{d.recommendation}</p>
                </div>
                {d.evidence.length > 0 && (
                  <div className="p-4">
                    <h3 className="mb-2 text-sm font-semibold">На чому ґрунтується висновок <span className="font-normal text-muted-foreground">– правило спрацювало повністю</span></h3>
                    <ul className="divide-y">
                      {d.evidence.map((e, k) => (
                        <li key={k} className="flex items-center gap-3 py-2 text-sm">
                          {e.ok ? <Check className="size-4 text-ok" aria-label="виконано" /> : <Minus className="size-4 text-muted-foreground" aria-label="не виконано" />}
                          <span>{e.text}</span>
                          <span className="num ml-auto whitespace-nowrap">{e.value}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {d.alternatives.map((a, k) => (
                  <p key={k} className="flex justify-between border-t p-3 px-4 text-sm text-muted-foreground">
                    <span>Можлива причина: {a.name}</span><span className="num">{a.ok} з {a.total} умов</span>
                  </p>
                ))}
              </>
            )}
          </section>
          <MetricChart targetId={inc.target_id} metric={inc.metric} instance={inc.instance} range="1h" title={`${metricLabel(inc.metric, inc.instance)} за останню годину`} />
        </div>

        <section aria-label="Хронологія" className="h-fit rounded-xl border bg-card p-4 shadow-sm">
          <h2 className="mb-3 font-semibold">Хронологія</h2>
          <ol className="grid gap-3">
            {inc.events.map((e, k) => (
              <li key={k} className="grid grid-cols-[48px_12px_1fr] items-start gap-2 text-sm">
                <time className="num text-muted-foreground" dateTime={e.ts} title={dateTime(e.ts)}>{time(e.ts)}</time>
                <span className={`mt-1.5 size-2.5 rounded-full ${DOT[e.type] ?? 'bg-off'}`} aria-hidden="true" />
                <span>{eventText(e, inc.metric)}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <Dialog open={resolving} onOpenChange={(o) => { setResolving(o); if (!o) form.reset() }}>
        <DialogContent>
          <form onSubmit={resolve} className="grid gap-4" noValidate>
            <DialogHeader>
              <DialogTitle>Закрити INC-{inc.id} вручну?</DialogTitle>
              <DialogDescription>Інцидент закриється, навіть якщо значення ще не повернулося в норму. Коментар з’явиться в хронології – колеги побачать, чому його закрито.</DialogDescription>
            </DialogHeader>
            <Field id="comment" label="Коментар" required error={form.formState.errors.comment?.message}>
              {(p) => <Textarea rows={3} {...p} {...form.register('comment')} />}
            </Field>
            {form.formState.errors.root?.message && <p role="alert" className="text-sm text-crit">{form.formState.errors.root.message}</p>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setResolving(false)}>Скасувати</Button>
              <Button type="submit" variant="destructive" disabled={form.formState.isSubmitting}>Закрити інцидент</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
