import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHead } from '@/components/small'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, ApiError } from '@/lib/api'
import { metricLabel, metricUnit } from '@/lib/metrics'
import { useTargets, useThresholds } from '@/lib/queries'
import type { ThresholdItem } from '@/lib/types'

const AGG: Record<string, string> = { last: 'останнє значення', avg: 'середнє', max: 'максимум', delta: 'приріст' }
const SOURCE: Record<ThresholdItem['source'], string> = { default: 'Типовий', template: 'Мій шаблон', target: 'Для об’єкта' }
const num = (v: string): number | null => (v.trim() === '' ? null : Number(v.replace(',', '.')))

function Row({ item, scope }: { item: ThresholdItem; scope: number | undefined }) {
  const qc = useQueryClient()
  const [warn, setWarn] = useState(item.warn?.toString() ?? '')
  const [crit, setCrit] = useState(item.crit?.toString() ?? '')
  const [duration, setDuration] = useState(String(item.duration_s))
  const own = scope === undefined ? item.source === 'template' : item.source === 'target'
  const unit = metricUnit(item.metric)
  const after = () => qc.invalidateQueries({ queryKey: ['thresholds'] })
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : 'Не вдалося зберегти')

  const save = async () => {
    try {
      await api('/thresholds', { method: 'PUT', body: { metric: item.metric, target_id: scope, warn: item.levels_editable ? num(warn) : null,
        crit: item.levels_editable ? num(crit) : null, duration_s: Number(duration) } })
      toast.success('Збережено')
      after()
    } catch (e) { fail(e) }
  }
  const reset = async () => {
    try {
      await api('/thresholds', { method: 'DELETE', params: { metric: item.metric, target_id: scope } })
      toast.success('Повернено типове значення')
      after()
    } catch (e) { fail(e) }
  }
  const label = metricLabel(item.metric)
  const field = (name: string, value: string, set: (v: string) => void, disabled = false) => (
    <Input aria-label={`${label}: ${name}`} inputMode="decimal" className="num w-24" value={disabled ? '' : value} placeholder={disabled ? '–' : ''} disabled={disabled}
      onChange={(e) => set(e.target.value)} />
  )
  return (
    <TableRow>
      <TableCell><span className="font-medium">{label}</span><br /><span className="text-xs text-muted-foreground">{AGG[item.agg] ?? item.agg}{item.window_s ? ` за ${Math.round(item.window_s / 60)} хв` : ''}{unit ? `, ${unit}` : ''}</span></TableCell>
      <TableCell>{field('попередження', warn, setWarn, !item.levels_editable)}</TableCell>
      <TableCell>{field('критичний', crit, setCrit, !item.levels_editable)}</TableCell>
      <TableCell>{field('тривалість, с', duration, setDuration)}</TableCell>
      <TableCell className="text-sm text-muted-foreground">{SOURCE[item.source]}</TableCell>
      <TableCell className="whitespace-nowrap">
        <Button size="sm" onClick={save}>Зберегти</Button>{' '}
        {own && <Button size="sm" variant="outline" onClick={reset}>Скинути</Button>}
      </TableCell>
    </TableRow>
  )
}

function Thresholds() {
  const targets = useTargets()
  const [scope, setScope] = useState<number | undefined>(undefined)
  const q = useThresholds(scope)
  return (
    <section aria-label="Порогові значення" className="grid gap-4">
      <p className="max-w-3xl text-sm text-muted-foreground">
        Інцидент відкривається, коли значення тримається за порогом щонайменше стільки секунд, скільки вказано в колонці «Тривалість». Налаштування для одного об’єкта
        мають перевагу над шаблоном для всіх, а шаблон – над типовими значеннями.
      </p>
      <label className="grid w-fit gap-1 text-sm font-medium">Для кого
        <select className="h-9 rounded-md border bg-background px-3 text-sm font-normal" value={scope ?? ''} onChange={(e) => setScope(e.target.value ? Number(e.target.value) : undefined)}>
          <option value="">Усі мої об’єкти (шаблон)</option>
          {targets.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </label>
      {q.isPending ? <Skeleton className="h-64 w-full" /> : (
        <div className="overflow-x-auto rounded-xl border bg-card shadow-sm">
          <Table>
            <TableHeader>
              <TableRow><TableHead>Метрика</TableHead><TableHead>Попередження</TableHead><TableHead>Критичний</TableHead><TableHead>Тривалість, с</TableHead><TableHead>Джерело</TableHead><TableHead /></TableRow>
            </TableHeader>
            <TableBody>
              {q.data?.map((item) => <Row key={`${scope}-${item.metric}-${item.source}-${item.warn}-${item.crit}-${item.duration_s}`} item={item} scope={scope} />)}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  )
}

export function SettingsPage() {
  document.title = 'Налаштування – Vigil'
  return (
    <>
      <PageHead title="Налаштування" subtitle="Порогові значення та правила виведення причин" />
      <Thresholds />
    </>
  )
}
