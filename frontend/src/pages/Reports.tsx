import { Download } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHead } from '@/components/small'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getToken } from '@/lib/auth'
import { duration, num } from '@/lib/format'
import { metricLabel, metricUnit, TYPE_LABEL } from '@/lib/metrics'
import { reportParams, useReport, type ReportRange } from '@/lib/queries'
import type { ReportRow } from '@/lib/types'

const RANGES: [ReportRange, string][] = [['24h', '24 години'], ['7d', '7 днів'], ['30d', '30 днів']]

const secs = (s: number | null) => (s == null ? '–' : duration(new Date(0).toISOString(), new Date(s * 1000).toISOString()))
const stats = (r: ReportRow) =>
  Object.entries(r.metrics).map(([m, v]) => `${metricLabel(m)}: ${num(v.avg)} / ${num(v.max)}${metricUnit(m) ? ' ' + metricUnit(m) : ''}`).join('; ') || '–'

/** CSV віддає бекенд; завантажуємо з токеном і зберігаємо як файл (звичайне посилання заголовка Authorization не передає). */
async function downloadCsv(range: ReportRange) {
  const q = new URLSearchParams({ ...reportParams(range), format: 'csv' })
  const res = await fetch(`/api/reports?${q}`, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!res.ok) throw new Error('Не вдалося сформувати файл')
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: `vigil-report-${range}.csv` })
  a.click()
  URL.revokeObjectURL(url)
}

export function ReportsPage() {
  document.title = 'Звіти – Vigil'
  const [range, setRange] = useState<ReportRange>('7d')
  const q = useReport(range)
  const worst = q.data?.rows.length ? Math.min(...q.data.rows.map((r) => r.availability_pct)) : null

  return (
    <>
      <PageHead title="Звіти" subtitle="Доступність, інциденти та навантаження за обраний період"
        actions={<Button variant="outline" size="sm" onClick={() => downloadCsv(range).catch((e) => toast.error(e.message))}><Download aria-hidden="true" />Експорт CSV</Button>} />
      <div className="flex gap-2" role="group" aria-label="Період">
        {RANGES.map(([k, l]) => <Button key={k} size="sm" variant={range === k ? 'default' : 'outline'} aria-pressed={range === k} onClick={() => setRange(k)}>{l}</Button>)}
      </div>

      {q.isPending ? <Skeleton className="h-64 w-full" /> : q.isError ? <p role="alert" className="text-sm text-crit">Не вдалося побудувати звіт</p> : (
        <>
          <dl className="grid gap-3 sm:grid-cols-3">
            {[['Інцидентів за період', String(q.data.incidents)], ['З них критичних', String(q.data.critical)],
              ['Найнижча доступність', worst == null ? '–' : `${num(worst)} %`]].map(([t, v]) => (
              <div key={t} className="rounded-xl border bg-card p-4 shadow-sm">
                <dt className="text-sm text-muted-foreground">{t}</dt>
                <dd className="num mt-1 text-2xl font-semibold">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="overflow-x-auto rounded-xl border bg-card shadow-sm">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Об’єкт</TableHead><TableHead>Тип</TableHead><TableHead>Доступність</TableHead><TableHead>Інциденти</TableHead>
                  <TableHead>Сер. виявлення</TableHead><TableHead>Сер. відновлення</TableHead><TableHead>Середнє / максимум</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {q.data.rows.map((r) => (
                  <TableRow key={r.target_id}>
                    <TableCell><Link to={`/targets/${r.target_id}`} className="font-medium hover:underline">{r.name}</Link></TableCell>
                    <TableCell>{TYPE_LABEL[r.type] ?? r.type}</TableCell>
                    <TableCell className="num">{num(r.availability_pct)} %</TableCell>
                    <TableCell className="num">{r.incidents}{r.critical > 0 && <span className="ml-1 text-crit">({r.critical} крит.)</span>}</TableCell>
                    <TableCell className="num">{secs(r.mean_detect_s)}</TableCell>
                    <TableCell className="num">{secs(r.mean_recover_s)}</TableCell>
                    <TableCell className="text-sm">{stats(r)}</TableCell>
                  </TableRow>
                ))}
                {q.data.rows.length === 0 && <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground">Об’єктів ще немає</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>

          {q.data.top_causes.length > 0 && (
            <section aria-label="Найчастіші причини" className="rounded-xl border bg-card p-4 shadow-sm">
              <h2 className="mb-2 font-semibold">Найчастіші причини</h2>
              <ol className="grid gap-1 text-sm">
                {q.data.top_causes.map((c) => <li key={c.cause} className="flex justify-between gap-3"><span>{c.cause}</span><span className="num text-muted-foreground">{c.count}</span></li>)}
              </ol>
            </section>
          )}
        </>
      )}
    </>
  )
}
