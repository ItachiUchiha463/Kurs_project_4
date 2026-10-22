import { AlertTriangle, Check, Circle, Minus, UserCheck, X, type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { IncidentStatus, Severity, Status } from '@/lib/types'

interface Meta {
  label: string
  icon: LucideIcon
  cls: string
}

// Колір стану ніколи не стоїть сам: поруч завжди іконка й текст (ТЗ розд. 11)
export const STATUS_META: Record<Status, Meta> = {
  ok: { label: 'Працює', icon: Check, cls: 'bg-ok-bg text-ok' },
  warning: { label: 'Попередження', icon: AlertTriangle, cls: 'bg-warn-bg text-warn' },
  critical: { label: 'Критичний стан', icon: X, cls: 'bg-crit-bg text-crit' },
  unavailable: { label: 'Недоступний', icon: Circle, cls: 'bg-off-bg text-off' },
  unknown: { label: 'Очікуємо дані', icon: Minus, cls: 'bg-off-bg text-off' },
}

const SEVERITY_META: Record<Severity, Meta> = {
  warning: { label: 'Попередження', icon: AlertTriangle, cls: 'bg-warn-bg text-warn' },
  critical: { label: 'Критичний', icon: X, cls: 'bg-crit-bg text-crit' },
}

function Pill({ meta, label }: { meta: Meta; label?: string }) {
  const Icon = meta.icon
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold', meta.cls)}>
      <Icon className="size-3.5" aria-hidden="true" />
      {label ?? meta.label}
    </span>
  )
}

export const StatusBadge = ({ status }: { status: Status }) => <Pill meta={STATUS_META[status]} />
export const SeverityBadge = ({ severity }: { severity: Severity }) => <Pill meta={SEVERITY_META[severity]} />

/** Підтверджений інцидент показуємо синім «хтось уже займається»; закритий – зеленим. */
export function IncidentStatusBadge({ status, severity }: { status: IncidentStatus; severity: Severity }) {
  if (status === 'acknowledged') return <Pill meta={{ label: 'Підтверджено', icon: UserCheck, cls: 'bg-ack-bg text-ack' }} />
  if (status === 'resolved') return <Pill meta={{ label: 'Закрито', icon: Check, cls: 'bg-ok-bg text-ok' }} />
  return <SeverityBadge severity={severity} />
}
