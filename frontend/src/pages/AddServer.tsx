import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import type { z } from 'zod'

import { applyApiError, Field } from '@/components/Field'
import { CommandBlock, LinkButton, PageHead } from '@/components/small'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { targetSchema } from '@/forms/schemas'
import { api } from '@/lib/api'
import { useTargets } from '@/lib/queries'
import type { TargetCreated } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Вміст agent.toml для сервера: host має збігатися з назвою об'єкта (ТЗ 5.1). */
export const agentConfig = (host: string, token: string) =>
  `server   = "${location.origin}"\ntoken    = "${token}"\nhost     = "${host}"\ninterval = 15`

const INSTALL = `git clone https://github.com/ItachiUchiha463/Kurs_project_4.git
cd Kurs_project_4/agent
pip install psutil httpx
# збережіть вміст вище як agent.toml у цій папці, потім:
python agent.py --config agent.toml`

const STEPS = ['Дані об’єкта', 'Встановлення агента', 'Перші дані']

function Steps({ current }: { current: number }) {
  return (
    <ol className="flex flex-wrap gap-4" aria-label="Кроки">
      {STEPS.map((s, i) => (
        <li key={s} className={cn('flex items-center gap-2 text-sm', i === current ? 'font-semibold' : 'text-muted-foreground')} aria-current={i === current ? 'step' : undefined}>
          <span className={cn('grid size-7 place-items-center rounded-full border text-xs font-bold', i < current && 'border-ok bg-ok-bg text-ok', i === current && 'border-primary bg-primary text-primary-foreground')}>
            {i < current ? <Check className="size-4" aria-label="виконано" /> : i + 1}
          </span>
          {s}
        </li>
      ))}
    </ol>
  )
}

function WaitForData({ created }: { created: TargetCreated }) {
  const { data } = useQuery({
    queryKey: ['target', created.id],
    queryFn: () => api<TargetCreated>(`/targets/${created.id}`),
    refetchInterval: (q) => (q.state.data?.last_seen ? false : 3000),
  })
  const got = !!data?.last_seen
  return (
    <div className="grid gap-3 rounded-xl border bg-card p-5 shadow-sm" role="status" aria-live="polite">
      <h2 className="text-lg font-semibold">{got ? 'Готово! Перші дані отримано' : 'Очікуємо дані від агента…'}</h2>
      {!got && <p className="text-sm text-muted-foreground">Перемкнемося автоматично, щойно прийде перша метрика. Агент надсилає дані кожні 15 секунд.</p>}
      {got && <LinkButton to={`/targets/${created.id}`} className="w-fit">Відкрити сторінку «{created.name}»</LinkButton>}
    </div>
  )
}

export function AddServerPage() {
  document.title = 'Додати сервер – Vigil'
  const qc = useQueryClient()
  const servers = useTargets()
  const [created, setCreated] = useState<TargetCreated | null>(null)
  const [step, setStep] = useState(0)
  const [formError, setFormError] = useState<string | null>(null)
  const { register, handleSubmit, watch, setError, formState: { errors, isSubmitting } } = useForm<z.infer<typeof targetSchema>>({
    resolver: zodResolver(targetSchema), defaultValues: { type: 'server', name: '' },
  })
  const type = watch('type')

  const submit = handleSubmit(async (v) => {
    setFormError(null)
    try {
      const body = { name: v.name, type: v.type, address: v.type === 'service' ? v.address : undefined, host_id: v.host_id ? Number(v.host_id) : undefined }
      const res = await api<TargetCreated>('/targets', { method: 'POST', body })
      qc.invalidateQueries({ queryKey: ['targets'] })
      setCreated(res)
      setStep(res.type === 'server' ? 1 : 2)
    } catch (e) {
      setFormError(applyApiError(e, setError, ['name', 'address']))
    }
  })

  return (
    <>
      <Link to="/" className="text-sm font-medium text-primary hover:underline">← Дашборд</Link>
      <PageHead title="Додати об’єкт" />
      <Steps current={step} />

      {step === 0 && (
        <form onSubmit={submit} className="grid max-w-xl gap-4 rounded-xl border bg-card p-5 shadow-sm" noValidate>
          {formError && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{formError}</p>}
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">Що підключаємо</legend>
            {([['server', 'Сервер', 'Встановлюється агент: CPU, RAM, диски, мережа'], ['service', 'Вебсервіс', 'Перевіряємо за адресою (HTTP) з нашого сервера']] as const).map(([v, l, h]) => (
              <label key={v} className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 has-[:checked]:border-primary has-[:checked]:bg-accent">
                <input type="radio" value={v} className="mt-1" {...register('type')} />
                <span><b>{l}</b><br /><span className="text-sm text-muted-foreground">{h}</span></span>
              </label>
            ))}
          </fieldset>
          <Field id="name" label="Назва" required error={errors.name?.message} hint="Як він відображатиметься на дашборді. Для сервера – та сама, що в agent.toml">
            {(p) => <Input placeholder={type === 'server' ? 'web-01' : 'shop.example.ua'} {...p} {...register('name')} />}
          </Field>
          {type === 'service' && (
            <>
              <Field id="address" label="Адреса" required error={errors.address?.message} hint="Публічна адреса: внутрішні (10.x, localhost) сервіс не перевіряє – для них потрібен агент">
                {(p) => <Input inputMode="url" placeholder="https://shop.example.ua/health" {...p} {...register('address')} />}
              </Field>
              <Field id="host_id" label="Працює на сервері" hint="Необов’язково. Дає змогу пов’язати збій сервісу зі станом сервера">
                {(p) => (
                  <select className="h-9 rounded-md border bg-background px-3 text-sm" {...p} {...register('host_id')}>
                    <option value="">– не вказано –</option>
                    {servers.data?.filter((s) => s.type === 'server').map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                )}
              </Field>
            </>
          )}
          <Button type="submit" disabled={isSubmitting} className="w-fit">{isSubmitting ? 'Створюємо…' : 'Далі'}</Button>
        </form>
      )}

      {step === 1 && created?.agent_token && (
        <section className="grid max-w-2xl gap-4 rounded-xl border bg-card p-5 shadow-sm">
          <p>Виконайте на сервері <b>{created.name}</b>. Потрібен Python 3.11 або новіший.</p>
          <div>
            <h2 className="mb-1 text-sm font-semibold">1. Файл agent.toml</h2>
            <CommandBlock>{agentConfig(created.name, created.agent_token)}</CommandBlock>
          </div>
          <div>
            <h2 className="mb-1 text-sm font-semibold">2. Встановлення й запуск</h2>
            <CommandBlock>{INSTALL}</CommandBlock>
          </div>
          <p className="text-sm text-muted-foreground">Токен показується лише зараз. Агент лише надсилає дані – вхідні порти відкривати не треба.</p>
          <Button className="w-fit" onClick={() => setStep(2)}>Я виконав команди</Button>
        </section>
      )}

      {step === 2 && created && (created.type === 'server' ? <WaitForData created={created} /> : (
        <div className="grid gap-3 rounded-xl border bg-card p-5 shadow-sm">
          <h2 className="text-lg font-semibold">Перевірки запущено</h2>
          <p className="text-sm text-muted-foreground">Перший результат з’явиться протягом хвилини. Збій сервісу відкриє інцидент після двох невдалих перевірок.</p>
          <LinkButton to={`/targets/${created.id}`} className="w-fit">Відкрити сторінку «{created.name}»</LinkButton>
        </div>
      ))}
    </>
  )
}
