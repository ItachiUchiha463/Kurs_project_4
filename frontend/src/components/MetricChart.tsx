import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Skeleton } from '@/components/ui/skeleton'
import { dateTime, num, time } from '@/lib/format'
import { METRICS, metricLabel, metricUnit } from '@/lib/metrics'
import { useSeries, useThresholds, type Range } from '@/lib/queries'

interface Props {
  targetId: number
  metric: string
  instance?: string
  range: Range
  title?: string
}

/** Графік з пунктирними лініями порогів і текстовим підсумком під ним (доступність: графік сам по собі нічого не озвучує). */
export function MetricChart({ targetId, metric, instance = '', range, title }: Props) {
  const { data, isPending, isError } = useSeries(targetId, metric, instance, range)
  const eff = useThresholds(targetId).data?.find((t) => t.metric === metric)
  const meta = METRICS[metric] && { ...METRICS[metric], ...(eff && eff.direction !== 'equals' ? { warn: eff.warn ?? undefined, crit: eff.crit ?? undefined } : {}) }
  const unit = metricUnit(metric)
  const label = title ?? metricLabel(metric, instance)
  const fmt = range === '7d' || range === '30d' ? dateTime : time  // на довгих періодах одного часу замало: потрібна й дата

  const values = data?.map((p) => p.value) ?? []
  const summary = values.length
    ? `за період: мін ${num(Math.min(...values))}, макс ${num(Math.max(...values))}, зараз ${num(values[values.length - 1])}${unit ? ' ' + unit : ''}`
    : 'за цей період даних немає'
  const over = meta?.crit != null && values.some((v) => v > meta.crit!)

  return (
    <figure className="rounded-xl border bg-card p-4 shadow-sm" aria-label={`${label}: ${summary}`}>
      <figcaption className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        {values.length > 0 && <span className="num text-xl">{num(values[values.length - 1])}{unit && <small className="ml-1 text-xs text-muted-foreground">{unit}</small>}</span>}
      </figcaption>
      {isPending ? (
        <Skeleton className="h-44 w-full" />
      ) : isError ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Не вдалося завантажити дані</p>
      ) : (
        <div className="h-44" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 6, right: 40, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={fmt} minTickGap={48} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
              <YAxis domain={meta?.max ? [0, meta.max] : [0, 'auto']} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" width={46} />
              {meta?.warn != null && <ReferenceLine y={meta.warn} stroke="var(--warn)" strokeDasharray="4 4" label={{ value: 'попер.', position: 'right', fontSize: 10, fill: 'var(--warn)' }} />}
              {meta?.crit != null && <ReferenceLine y={meta.crit} stroke="var(--crit)" strokeDasharray="4 4" label={{ value: 'крит.', position: 'right', fontSize: 10, fill: 'var(--crit)' }} />}
              <Tooltip
                contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                labelFormatter={(ts) => fmt(String(ts))}
                formatter={(v) => [`${num(Number(v))}${unit ? ' ' + unit : ''}`, label]}
              />
              <Line type="monotone" dataKey="value" stroke="var(--primary)" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-2 text-xs text-muted-foreground">{summary}{over ? ', було вище критичного порогу' : ''}</p>
    </figure>
  )
}
