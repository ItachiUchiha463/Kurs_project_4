import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm, type FieldValues, type UseFormSetError } from 'react-hook-form'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import type { z } from 'zod'

import { Field, PasswordInput, useFormSubmit } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { forgotSchema, loginSchema, registerSchema, resetSchema } from '@/forms/schemas'
import { api } from '@/lib/api'
import { setToken } from '@/lib/auth'

function useAuthSubmit<T extends FieldValues>(path: string, setError: UseFormSetError<T>, fields: string[]) {
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const { formError, run } = useFormSubmit(setError, fields)
  const submit = (body: unknown, afterLogin?: string) => run(async () => {
    const { access_token } = await api<{ access_token: string }>(path, { method: 'POST', body })
    setToken(access_token)
    qc.clear()
    navigate(afterLogin ?? (location.state as { from?: string } | null)?.from ?? '/', { replace: true })
  })
  return { formError, submit }
}

export function LoginPage() {
  document.title = 'Вхід – Vigil'
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) })
  const { formError, submit } = useAuthSubmit('/auth/login', setError, ['email', 'password'])
  return (
    <form onSubmit={handleSubmit((v) => submit(v))} className="grid gap-4" noValidate>
      <div>
        <h1 className="text-2xl font-semibold">Вхід</h1>
        <p className="text-sm text-muted-foreground">Моніторинг ваших серверів і сервісів</p>
      </div>
      {formError && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{formError}</p>}
      <Field id="email" label="Email" required error={errors.email?.message}>
        {(p) => <Input type="email" autoComplete="username" {...p} {...register('email')} />}
      </Field>
      <Field id="password" label="Пароль" required error={errors.password?.message}>
        {(p) => <PasswordInput autoComplete="current-password" {...p} {...register('password')} />}
      </Field>
      <Button type="submit" disabled={isSubmitting}>{isSubmitting ? 'Входимо…' : 'Увійти'}</Button>
      <p className="text-sm text-muted-foreground"><Link to="/forgot" className="font-medium text-primary underline-offset-4 hover:underline">Забули пароль?</Link></p>
      <p className="text-sm text-muted-foreground">Немає облікового запису? <Link to="/register" className="font-medium text-primary underline-offset-4 hover:underline">Зареєструватися</Link></p>
    </form>
  )
}

export function RegisterPage() {
  document.title = 'Реєстрація – Vigil'
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema) })
  const { formError, submit } = useAuthSubmit('/auth/register', setError, ['full_name', 'email', 'password'])
  return (
    <form
      onSubmit={handleSubmit(({ repeat: _repeat, ...body }) => submit(body, '/targets/new'))}
      className="grid gap-4" noValidate>
      <div>
        <h1 className="text-2xl font-semibold">Реєстрація</h1>
        <p className="text-sm text-muted-foreground">Після реєстрації підключіть перший сервер</p>
      </div>
      {formError && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{formError}</p>}
      <Field id="full_name" label="Ім’я" required error={errors.full_name?.message}>
        {(p) => <Input autoComplete="name" {...p} {...register('full_name')} />}
      </Field>
      <Field id="email" label="Email" required error={errors.email?.message} hint="Це лише ваш логін, лист не надсилатиметься">
        {(p) => <Input type="email" autoComplete="username" {...p} {...register('email')} />}
      </Field>
      <Field id="password" label="Пароль" required error={errors.password?.message} hint="Щонайменше 8 символів, літера й цифра">
        {(p) => <PasswordInput autoComplete="new-password" {...p} {...register('password')} />}
      </Field>
      <Field id="repeat" label="Повторіть пароль" required error={errors.repeat?.message}>
        {(p) => <PasswordInput autoComplete="new-password" {...p} {...register('repeat')} />}
      </Field>
      <Button type="submit" disabled={isSubmitting}>{isSubmitting ? 'Створюємо…' : 'Зареєструватися'}</Button>
      <p className="text-sm text-muted-foreground">Уже є обліковий запис? <Link to="/login" className="font-medium text-primary underline-offset-4 hover:underline">Увійти</Link></p>
    </form>
  )
}

/** Скидання пароля (ТЗ 2.2): посилання приходить у Telegram, прив'язаний до облікового запису. */
export function ForgotPage() {
  document.title = 'Скидання пароля – Vigil'
  const [sent, setSent] = useState(false)
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<z.infer<typeof forgotSchema>>({ resolver: zodResolver(forgotSchema) })
  const { formError, run } = useFormSubmit(setError, ['email'])
  const submit = handleSubmit((body) => run(async () => {
    await api('/auth/forgot', { method: 'POST', body })
    setSent(true)
  }))
  if (sent) {
    return (
      <div className="grid gap-4" role="status">
        <h1 className="text-2xl font-semibold">Перевірте Telegram</h1>
        <p className="text-sm">Якщо до цього облікового запису прив’язано Telegram, ми надіслали туди посилання для скидання пароля. Воно діє 30 хвилин.</p>
        <p className="text-sm text-muted-foreground">Telegram не прив’язано? Тоді скинути пароль може лише власник сервісу.</p>
        <Link to="/login" className="text-sm font-medium text-primary hover:underline">← До входу</Link>
      </div>
    )
  }
  return (
    <form onSubmit={submit} className="grid gap-4" noValidate>
      <div>
        <h1 className="text-2xl font-semibold">Скидання пароля</h1>
        <p className="text-sm text-muted-foreground">Посилання надійде у ваш Telegram</p>
      </div>
      {formError && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{formError}</p>}
      <Field id="email" label="Email" required error={errors.email?.message}>
        {(p) => <Input type="email" autoComplete="username" {...p} {...register('email')} />}
      </Field>
      <Button type="submit" disabled={isSubmitting}>{isSubmitting ? 'Надсилаємо…' : 'Надіслати посилання'}</Button>
      <Link to="/login" className="text-sm font-medium text-primary hover:underline">← До входу</Link>
    </form>
  )
}

export function ResetPage() {
  document.title = 'Новий пароль – Vigil'
  const token = useSearchParams()[0].get('token') ?? ''
  const navigate = useNavigate()
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema) })
  const { formError, run } = useFormSubmit(setError, ['password'])
  const submit = handleSubmit(({ password }) => run(async () => {
    await api('/auth/reset', { method: 'POST', body: { token, password } })
    navigate('/login', { replace: true, state: { reset: true } })
  }))
  return (
    <form onSubmit={submit} className="grid gap-4" noValidate>
      <div>
        <h1 className="text-2xl font-semibold">Новий пароль</h1>
        <p className="text-sm text-muted-foreground">Після зміни всі ваші сеанси на інших пристроях завершаться</p>
      </div>
      {!token && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">Посилання неповне. Запросіть нове на сторінці «Забули пароль?»</p>}
      {formError && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{formError}</p>}
      <Field id="password" label="Новий пароль" required error={errors.password?.message} hint="Щонайменше 8 символів, літера й цифра">
        {(p) => <PasswordInput autoComplete="new-password" {...p} {...register('password')} />}
      </Field>
      <Field id="repeat" label="Повторіть пароль" required error={errors.repeat?.message}>
        {(p) => <PasswordInput autoComplete="new-password" {...p} {...register('repeat')} />}
      </Field>
      <Button type="submit" disabled={isSubmitting || !token}>{isSubmitting ? 'Зберігаємо…' : 'Змінити пароль'}</Button>
    </form>
  )
}
