import { Eye, EyeOff } from 'lucide-react'
import { forwardRef, useState, type ComponentProps, type ReactNode } from 'react'
import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'

interface FieldProps {
  id: string
  label: string
  error?: string
  hint?: string
  required?: boolean
  children: (props: { id: string; 'aria-invalid': boolean; 'aria-describedby': string }) => ReactNode
}

/** Підпис, підказка й помилка біля поля, зв'язані через aria-describedby (помилка не лише червоним). */
export function Field({ id, label, error, hint, required, children }: FieldProps) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required && <span className="text-crit" aria-hidden="true"> *</span>}
      </Label>
      {children({ id, 'aria-invalid': !!error, 'aria-describedby': `${id}-msg` })}
      <p id={`${id}-msg`} className={error ? 'text-sm text-crit' : 'text-xs text-muted-foreground'} role={error ? 'alert' : undefined}>
        {error ?? hint}
      </p>
    </div>
  )
}

export const PasswordInput = forwardRef<HTMLInputElement, ComponentProps<typeof Input>>((props, ref) => {
  const [shown, setShown] = useState(false)
  return (
    <div className="flex gap-2">
      <Input ref={ref} type={shown ? 'text' : 'password'} {...props} />
      <Button type="button" variant="outline" size="icon" onClick={() => setShown((s) => !s)} aria-pressed={shown}
        aria-label={shown ? 'Сховати пароль' : 'Показати пароль'}>
        {shown ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
      </Button>
    </div>
  )
})
PasswordInput.displayName = 'PasswordInput'

/** Спільна відправка форм: скидає загальну помилку, виконує запит, а збій розкладає по полях (applyApiError). */
export function useFormSubmit<T extends FieldValues>(setError: UseFormSetError<T>, fields: string[]) {
  const [formError, setFormError] = useState<string | null>(null)
  const run = async (action: () => Promise<unknown>) => {
    setFormError(null)
    try {
      await action()
    } catch (e) {
      setFormError(applyApiError(e, setError, fields))
    }
  }
  return { formError, run }
}

/** Помилки 422 від бекенда розкладаємо по тих самих полях; решту повертаємо текстом для загального повідомлення. */
export function applyApiError<T extends FieldValues>(err: unknown, setError: UseFormSetError<T>, fields: string[]): string | null {
  if (!(err instanceof ApiError)) return 'Сталася помилка'
  let placed = false
  for (const d of err.details) {
    if (d.field && fields.includes(d.field)) {
      setError(d.field as Path<T>, { message: d.message })
      placed = true
    }
  }
  return placed ? null : err.message
}
