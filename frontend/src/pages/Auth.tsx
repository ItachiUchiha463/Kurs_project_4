import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useForm, type FieldValues, type UseFormSetError } from 'react-hook-form'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import type { z } from 'zod'

import { Field, PasswordInput, useFormSubmit } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { forgotSchema, loginSchema, registerSchema, resetSchema } from '@/forms/schemas'
import { api, ApiError } from '@/lib/api'
import { setToken } from '@/lib/auth'

function useAuthSubmit<T extends FieldValues>(path: string, setError: UseFormSetError<T>, fields: string[]) {
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const { formError, run } = useFormSubmit(setError, fields)
  const submit = (body: unknown, afterLogin?: string, onPending?: () => void) => run(async () => {
    const { access_token } = await api<{ access_token: string | null }>(path, { method: 'POST', body })
    if (!access_token) return onPending?.()  // реєстрація: спершу потрібно підтвердити пошту
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
  const [sentTo, setSentTo] = useState<string | null>(null)
  if (sentTo) {
    return (
      <div className="grid gap-4" role="status">
        <h1 className="text-2xl font-semibold">Перевірте пошту</h1>
        <p className="text-sm">Ми надіслали лист на <b>{sentTo}</b>. Відкрийте посилання з нього, щоб завершити реєстрацію. Посилання діє 24 години.</p>
        <p className="text-sm text-muted-foreground">Листа немає? Перевірте «Спам» або спробуйте увійти: ми надішлемо новий.</p>
        <Link to="/login" className="text-sm font-medium text-primary hover:underline">← До входу</Link>
      </div>
    )
  }
  return (
    <form
      onSubmit={handleSubmit(({ repeat: _repeat, ...body }) => submit(body, '/targets/new', () => setSentTo(body.email)))}
      className="grid gap-4" noValidate>
      <div>
        <h1 className="text-2xl font-semibold">Реєстрація</h1>
        <p className="text-sm text-muted-foreground">Після реєстрації підключіть перший сервер</p>
      </div>
      {formError && <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{formError}</p>}
      <Field id="full_name" label="Ім’я" required error={errors.full_name?.message}>
        {(p) => <Input autoComplete="name" {...p} {...register('full_name')} />}
      </Field>
      <Field id="email" label="Email" required error={errors.email?.message} hint="Логін; на цю адресу надійде лист для підтвердження, нею ж скидається пароль">
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

/** Скидання пароля (ТЗ 2.2): посилання приходить на пошту і в Telegram, якщо він прив'язаний. */
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
        <h1 className="text-2xl font-semibold">Перевірте пошту</h1>
        <p className="text-sm">Якщо такий обліковий запис є, ми надіслали посилання для скидання пароля на його пошту, а також у Telegram, якщо він прив’язаний. Воно діє 30 хвилин.</p>
        <p className="text-sm text-muted-foreground">Листа немає? Перевірте «Спам». Пошту має бути підтверджено під час реєстрації.</p>
        <Link to="/login" className="text-sm font-medium text-primary hover:underline">← До входу</Link>
      </div>
    )
  }
  return (
    <form onSubmit={submit} className="grid gap-4" noValidate>
      <div>
        <h1 className="text-2xl font-semibold">Скидання пароля</h1>
        <p className="text-sm text-muted-foreground">Посилання надійде на вашу пошту</p>
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

/** Посилання з листа (ТЗ 2.2): підтверджує пошту й одразу входить в обліковий запис. */
export function VerifyPage() {
  document.title = 'Підтвердження пошти – Vigil'
  const token = useSearchParams()[0].get('token') ?? ''
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(token ? null : 'Посилання неповне. Спробуйте увійти: ми надішлемо новий лист')
  const started = useRef(false)  // посилання одноразове: подвійний запуск ефекту (StrictMode) не має його «спалити»
  useEffect(() => {
    if (!token || started.current) return
    started.current = true
    api<{ access_token: string }>('/auth/verify', { method: 'POST', body: { token } })
      .then(({ access_token }) => {
        setToken(access_token)
        qc.clear()
        navigate('/targets/new', { replace: true })
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Сталася помилка'))
  }, [token, navigate, qc])
  if (error) {
    return (
      <div className="grid gap-4">
        <h1 className="text-2xl font-semibold">Пошту не підтверджено</h1>
        <p role="alert" className="rounded-lg bg-crit-bg p-3 text-sm text-crit">{error}</p>
        <Link to="/login" className="text-sm font-medium text-primary hover:underline">← До входу</Link>
      </div>
    )
  }
  return <p role="status" className="text-sm text-muted-foreground">Підтверджуємо пошту…</p>
}
