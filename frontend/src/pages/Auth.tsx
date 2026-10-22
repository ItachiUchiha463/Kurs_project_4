import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import type { z } from 'zod'

import { applyApiError, Field, PasswordInput } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { loginSchema, registerSchema } from '@/forms/schemas'
import { api } from '@/lib/api'
import { setToken } from '@/lib/auth'

function useAuthSubmit(path: string) {
  const [formError, setFormError] = useState<string | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const submit = async (body: unknown, onApiError: (e: unknown) => string | null, afterLogin?: string) => {
    setFormError(null)
    try {
      const { access_token } = await api<{ access_token: string }>(path, { method: 'POST', body })
      setToken(access_token)
      qc.clear()
      navigate(afterLogin ?? (location.state as { from?: string } | null)?.from ?? '/', { replace: true })
    } catch (e) {
      setFormError(onApiError(e))
    }
  }
  return { formError, submit }
}

export function LoginPage() {
  document.title = 'Вхід – Vigil'
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) })
  const { formError, submit } = useAuthSubmit('/auth/login')
  return (
    <form onSubmit={handleSubmit((v) => submit(v, (e) => applyApiError(e, setError, ['email', 'password'])))} className="grid gap-4" noValidate>
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
      <p className="text-sm text-muted-foreground">Немає облікового запису? <Link to="/register" className="font-medium text-primary underline-offset-4 hover:underline">Зареєструватися</Link></p>
    </form>
  )
}

export function RegisterPage() {
  document.title = 'Реєстрація – Vigil'
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema) })
  const { formError, submit } = useAuthSubmit('/auth/register')
  return (
    <form
      onSubmit={handleSubmit(({ repeat: _repeat, ...body }) => submit(body, (e) => applyApiError(e, setError, ['full_name', 'email', 'password']), '/targets/new'))}
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
