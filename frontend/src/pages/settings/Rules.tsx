import { useQueryClient } from '@tanstack/react-query'
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { api, ApiError } from '@/lib/api'
import { METRICS, metricLabel } from '@/lib/metrics'
import { useRules, useTargets } from '@/lib/queries'
import type { Rule, RuleCondition, RuleTest } from '@/lib/types'

const TYPES: [string, string][] = [['server', 'Сервер'], ['service', 'Сервіс'], ['container', 'Контейнер'], ['database', 'База даних']]
const SCOPES: Record<RuleCondition['scope'], string> = { self: 'сам об’єкт', host: 'його сервер', siblings: 'сусідні об’єкти сервера' }
const AGGS: Record<string, string> = { last: 'останнє', avg: 'середнє', max: 'максимум', min: 'мінімум', delta: 'приріст' }
const OPS = ['>', '>=', '<', '<=', '==']
const SIBLING_TYPES = [['container', 'контейнери'], ['database', 'бази даних'], ['service', 'сервіси']]

/** Умова людською мовою: «сам об’єкт: CPU, середнє за 5 хв > 90». */
export function conditionText(c: RuleCondition) {
  const win = c.agg !== 'last' && c.window_s ? ` за ${Math.round(c.window_s / 60) || 1} хв` : ''
  const who = c.scope === 'siblings' ? `сусідні (${SIBLING_TYPES.find(([k]) => k === c.sibling_type)?.[1] ?? '?'}, ${c.match === 'all' ? 'усі' : 'хоч один'})` : SCOPES[c.scope]
  return `${who}: ${metricLabel(c.metric)}, ${AGGS[c.agg]}${win} ${c.op} ${c.value}`
}

interface CondForm { scope: RuleCondition['scope']; metric: string; op: string; value: string; agg: string; minutes: string; sibling_type: string; match: string }
interface RuleForm { name: string; cause: string; recommendation: string; priority: string; applies_to: string[]; conditions: CondForm[] }

const emptyCond = (): CondForm => ({ scope: 'self', metric: 'cpu_usage', op: '>', value: '', agg: 'last', minutes: '5', sibling_type: 'container', match: 'any' })
const emptyForm = (): RuleForm => ({ name: '', cause: '', recommendation: '', priority: '10', applies_to: ['server'], conditions: [emptyCond()] })
const toForm = (r: Rule): RuleForm => ({
  name: r.name, cause: r.cause, recommendation: r.recommendation, priority: String(r.priority), applies_to: r.applies_to,
  conditions: r.conditions.map((c) => ({ scope: c.scope, metric: c.metric, op: c.op, value: String(c.value), agg: c.agg, minutes: String(Math.round(c.window_s / 60) || 5),
    sibling_type: c.sibling_type ?? 'container', match: c.match })),
})
const toBody = (f: RuleForm) => ({
  name: f.name.trim(), cause: f.cause.trim(), recommendation: f.recommendation.trim(), priority: Number(f.priority) || 0, applies_to: f.applies_to,
  conditions: f.conditions.map((c) => ({
    scope: c.scope, metric: c.metric, op: c.op, value: Number(c.value.replace(',', '.')), agg: c.agg, window_s: c.agg === 'last' ? 0 : Math.round(Number(c.minutes) * 60),
    sibling_type: c.scope === 'siblings' ? c.sibling_type : null, match: c.match,
  })),
})
const select = 'h-9 rounded-md border bg-background px-2 text-sm'

function Editor({ rule, onClose }: { rule: Rule | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState<RuleForm>(rule ? toForm(rule) : emptyForm())
  const [error, setError] = useState<string | null>(null)
  const setCond = (i: number, patch: Partial<CondForm>) => setF({ ...f, conditions: f.conditions.map((c, k) => (k === i ? { ...c, ...patch } : c)) })
  const toggleType = (t: string) => setF({ ...f, applies_to: f.applies_to.includes(t) ? f.applies_to.filter((x) => x !== t) : [...f.applies_to, t] })

  const save = async () => {
    setError(null)
    try {
      await api(rule ? `/rules/${rule.id}` : '/rules', { method: rule ? 'PATCH' : 'POST', body: toBody(f) })
      toast.success(rule ? 'Правило збережено' : 'Правило створено')
      qc.invalidateQueries({ queryKey: ['rules'] })
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? [e.message, ...e.details.map((d) => d.message)].filter((v, i, a) => a.indexOf(v) === i).join('. ') : 'Не вдалося зберегти')
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{rule ? 'Редагувати правило' : 'Нове правило'}</DialogTitle>
          <DialogDescription>Усі умови поєднуються через «І». Перша умова має описувати сам об’єкт і метрику, для якої є поріг: за нею система вирішує, чи розглядати правило.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          {error && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{error}</p>}
          <label className="grid gap-1 text-sm font-medium">Назва<Input value={f.name} maxLength={100} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <fieldset className="flex flex-wrap gap-3 text-sm">
            <legend className="mb-1 font-medium">Для яких об’єктів</legend>
            {TYPES.map(([k, l]) => <label key={k} className="flex items-center gap-1.5"><input type="checkbox" checked={f.applies_to.includes(k)} onChange={() => toggleType(k)} />{l}</label>)}
          </fieldset>
          <div className="grid gap-2">
            <h3 className="text-sm font-medium">Умови</h3>
            {f.conditions.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border p-2" role="group" aria-label={`Умова ${i + 1}`}>
                <select className={select} aria-label="Про що" value={c.scope} onChange={(e) => setCond(i, { scope: e.target.value as CondForm['scope'] })}>
                  {Object.entries(SCOPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                {c.scope === 'siblings' && (
                  <>
                    <select className={select} aria-label="Тип сусідів" value={c.sibling_type} onChange={(e) => setCond(i, { sibling_type: e.target.value })}>
                      {SIBLING_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                    <select className={select} aria-label="Квантор" value={c.match} onChange={(e) => setCond(i, { match: e.target.value })}>
                      <option value="any">хоч один</option><option value="all">усі</option>
                    </select>
                  </>
                )}
                <select className={select} aria-label="Метрика" value={c.metric} onChange={(e) => setCond(i, { metric: e.target.value })}>
                  {Object.keys(METRICS).map((m) => <option key={m} value={m}>{metricLabel(m)}</option>)}
                </select>
                <select className={select} aria-label="Агрегація" value={c.agg} onChange={(e) => setCond(i, { agg: e.target.value })}>
                  {Object.entries(AGGS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                {c.agg !== 'last' && <Input aria-label="Вікно, хв" className="num w-20" inputMode="numeric" value={c.minutes} onChange={(e) => setCond(i, { minutes: e.target.value })} />}
                {c.agg !== 'last' && <span className="text-sm text-muted-foreground">хв</span>}
                <select className={select} aria-label="Оператор" value={c.op} onChange={(e) => setCond(i, { op: e.target.value })}>{OPS.map((o) => <option key={o}>{o}</option>)}</select>
                <Input aria-label="Значення" className="num w-24" inputMode="decimal" value={c.value} onChange={(e) => setCond(i, { value: e.target.value })} />
                {f.conditions.length > 1 && <Button type="button" variant="ghost" size="icon" aria-label={`Видалити умову ${i + 1}`} onClick={() => setF({ ...f, conditions: f.conditions.filter((_, k) => k !== i) })}><X aria-hidden="true" /></Button>}
              </div>
            ))}
            {f.conditions.length < 6 && <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => setF({ ...f, conditions: [...f.conditions, { ...emptyCond(), scope: 'host' }] })}><Plus aria-hidden="true" />Додати умову</Button>}
          </div>
          <label className="grid gap-1 text-sm font-medium">Ймовірна причина<Input value={f.cause} maxLength={200} onChange={(e) => setF({ ...f, cause: e.target.value })} /></label>
          <label className="grid gap-1 text-sm font-medium">Рекомендація<Textarea value={f.recommendation} maxLength={1000} onChange={(e) => setF({ ...f, recommendation: e.target.value })} /></label>
          <label className="grid w-fit gap-1 text-sm font-medium">Пріоритет (0–100)<Input className="num w-24" inputMode="numeric" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })} /></label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Скасувати</Button>
          <Button onClick={save}>Зберегти</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TestDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const targets = useTargets()
  const options = (targets.data ?? []).filter((t) => rule.applies_to.includes(t.type))
  const [target, setTarget] = useState('')
  const [result, setResult] = useState<RuleTest | null>(null)
  const run = async () => {
    try { setResult(await api<RuleTest>(`/rules/${rule.id}/test`, { method: 'POST', params: { target_id: Number(target) } })) }
    catch (e) { toast.error(e instanceof ApiError ? e.message : 'Не вдалося перевірити') }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Перевірити «{rule.name}»</DialogTitle>
          <DialogDescription>Покаже, чи спрацювало б правило на поточних даних обраного об’єкта.</DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          <select className={`${select} flex-1`} aria-label="Об’єкт" value={target} onChange={(e) => { setTarget(e.target.value); setResult(null) }}>
            <option value="">– оберіть об’єкт –</option>
            {options.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <Button disabled={!target} onClick={run}>Перевірити</Button>
        </div>
        {options.length === 0 && <p className="text-sm text-muted-foreground">Немає об’єктів потрібного типу.</p>}
        {result && (
          <div role="status" className="grid gap-2">
            <p className={result.matched ? 'font-semibold text-ok' : 'font-semibold text-muted-foreground'}>{result.matched ? 'Правило спрацювало б: усі умови виконано' : `Не спрацювало б: виконано ${Math.round(result.ratio * 100)} % умов`}</p>
            <ul className="grid gap-1 text-sm">
              {result.evidence.map((e, i) => (
                <li key={i} className="flex items-start gap-2">
                  {e.ok ? <Check className="mt-0.5 size-4 text-ok" aria-label="виконано" /> : <X className="mt-0.5 size-4 text-crit" aria-label="не виконано" />}
                  <span>{e.text}: <span className="num">{e.value}</span></span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <DialogFooter><Button variant="outline" onClick={onClose}>Закрити</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function Rules() {
  const q = useRules()
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Rule | 'new' | null>(null)
  const [testing, setTesting] = useState<Rule | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['rules'] })
  const toggle = async (r: Rule) => {
    try { await api(`/rules/${r.id}/enabled`, { method: 'PUT', body: { enabled: !r.enabled } }); refresh() } catch { toast.error('Не вдалося змінити') }
  }
  const remove = async (r: Rule) => {
    if (!confirm(`Видалити правило «${r.name}»?`)) return
    try { await api(`/rules/${r.id}`, { method: 'DELETE' }); toast.success('Правило видалено'); refresh() } catch { toast.error('Не вдалося видалити') }
  }

  return (
    <section aria-label="Правила виведення причин" className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-muted-foreground">Правило каже, яку причину назвати, коли виконано всі його умови. Базові правила можна вимикати для себе, а власні – створювати й змінювати. Власне правило з тією ж кількістю умов має перевагу.</p>
        <Button onClick={() => setEditing('new')}><Plus aria-hidden="true" />Нове правило</Button>
      </div>
      {q.isPending ? <Skeleton className="h-64 w-full" /> : (
        <ul className="grid gap-3">
          {q.data?.map((r) => (
            <li key={r.id} className={`rounded-xl border bg-card p-4 shadow-sm ${r.enabled ? '' : 'opacity-60'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">{r.name}</h3>
                <span className="rounded-full border px-2 py-0.5 text-xs">{r.own ? 'Моє' : 'Базове'}</span>
                {!r.enabled && <span className="text-xs text-muted-foreground">вимкнено</span>}
                <span className="ml-auto flex flex-wrap gap-1">
                  <Button size="sm" variant="outline" onClick={() => setTesting(r)}>Перевірити</Button>
                  <Button size="sm" variant="outline" onClick={() => toggle(r)} aria-pressed={r.enabled}>{r.enabled ? 'Вимкнути' : 'Увімкнути'}</Button>
                  {r.own && <Button size="icon" variant="ghost" aria-label={`Редагувати «${r.name}»`} onClick={() => setEditing(r)}><Pencil aria-hidden="true" /></Button>}
                  {r.own && <Button size="icon" variant="ghost" aria-label={`Видалити «${r.name}»`} onClick={() => remove(r)}><Trash2 aria-hidden="true" /></Button>}
                </span>
              </div>
              <p className="mt-1 text-sm"><b>Причина:</b> {r.cause}</p>
              <p className="text-sm text-muted-foreground">Для: {r.applies_to.map((t) => TYPES.find(([k]) => k === t)?.[1] ?? t).join(', ')}</p>
              <ul className="mt-1 list-disc pl-5 text-sm text-muted-foreground">{r.conditions.map((c, i) => <li key={i}>{conditionText(c)}</li>)}</ul>
            </li>
          ))}
        </ul>
      )}
      {editing && <Editor rule={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {testing && <TestDialog rule={testing} onClose={() => setTesting(null)} />}
    </section>
  )
}
