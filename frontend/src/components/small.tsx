import { Check, Copy, Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { Link } from 'react-router-dom'

import { Button, buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { VariantProps } from 'class-variance-authority'
import { useLiveStatus } from '@/ws/live'

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const dark = resolvedTheme === 'dark'
  return (
    <Button variant="outline" size="icon" onClick={() => setTheme(dark ? 'light' : 'dark')} aria-label={dark ? 'Увімкнути світлу тему' : 'Увімкнути темну тему'}>
      {dark ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  )
}

export function LiveIndicator() {
  const s = useLiveStatus()
  const live = s === 'live'
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
      <span className={`size-2 rounded-full ${live ? 'bg-ok' : 'bg-warn'}`} aria-hidden="true" />
      {live ? 'Наживо' : s === 'connecting' ? 'Підключення…' : 'Перепідключення…'}
    </span>
  )
}

export function CommandBlock({ children, label = 'Скопіювати' }: { children: string; label?: string }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(children)
      setDone(true)
      setTimeout(() => setDone(false), 2000)
    } catch {
      toast.error('Не вдалося скопіювати: виділіть текст і скопіюйте вручну')
    }
  }
  return (
    <div className="relative rounded-lg bg-slate-900 p-3 pr-28 text-slate-100">
      <pre className="whitespace-pre-wrap break-all font-mono text-[13px] leading-relaxed [overflow-wrap:anywhere]"><code>{children}</code></pre>
      <Button size="sm" variant="secondary" className="absolute right-2 top-2" onClick={copy}>
        {done ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        {done ? 'Скопійовано' : label}
      </Button>
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed bg-card p-10 text-center">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}


type LinkButtonProps = VariantProps<typeof buttonVariants> & { to: string; external?: boolean; className?: string; children: ReactNode }

/** Посилання з виглядом кнопки (Button у цій збірці shadcn не має asChild). */
export function LinkButton({ to, external, variant, size, className, children }: LinkButtonProps) {
  const cls = cn(buttonVariants({ variant, size }), className)
  return external
    ? <a href={to} className={cls} target="_blank" rel="noreferrer">{children}</a>
    : <Link to={to} className={cls}>{children}</Link>
}
