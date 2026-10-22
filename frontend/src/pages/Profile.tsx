import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { LinkButton, PageHead } from '@/components/small'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { useMe } from '@/lib/queries'
import type { Me, Severity, TelegramLink } from '@/lib/types'

export function ProfilePage() {
  document.title = 'Профіль – Vigil'
  const me = useMe()
  const qc = useQueryClient()
  const [link, setLink] = useState<TelegramLink | null>(null)

  // поки користувач підключає бота, опитуємо профіль: після /start у Telegram прив'язка з'явиться сама
  useEffect(() => {
    if (!link || me.data?.telegram_linked) return
    const t = setInterval(() => qc.invalidateQueries({ queryKey: ['me'] }), 3000)
    return () => clearInterval(t)
  }, [link, me.data?.telegram_linked, qc])
  useEffect(() => { if (me.data?.telegram_linked && link) { setLink(null); toast.success('Telegram підключено') } }, [me.data?.telegram_linked, link])

  if (me.isPending) return <><PageHead title="Профіль" /><Skeleton className="h-48 w-full" /></>
  const u = me.data!

  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    try { await fn(); if (ok) toast.success(ok); qc.invalidateQueries({ queryKey: ['me'] }) }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Не вдалося') }
  }

  return (
    <>
      <PageHead title="Профіль" subtitle={`${u.full_name} · ${u.email}`} />

      <section className="grid max-w-2xl gap-4 rounded-xl border bg-card p-5 shadow-sm" aria-labelledby="tg">
        <h2 id="tg" className="text-lg font-semibold">Сповіщення в Telegram</h2>
        {u.telegram_linked ? (
          <>
            <p className="text-sm">Telegram підключено: повідомлення про інциденти приходитимуть у ваш чат із кнопкою «Підтвердити».</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => act(() => api('/me/telegram/test', { method: 'POST' }), 'Тестове повідомлення надіслано')}>Надіслати тестове</Button>
              <Button variant="outline" onClick={() => act(() => api('/me/telegram', { method: 'DELETE' }), 'Telegram відключено')}>Відключити</Button>
            </div>
          </>
        ) : link ? (
          <div className="grid gap-2" role="status">
            {link.url
              ? <LinkButton to={link.url} external className="w-fit">Відкрити бота в Telegram</LinkButton>
              : <p className="text-sm">Відкрийте бота й надішліть команду <code className="num">/start {link.code}</code></p>}
            <p className="text-sm text-muted-foreground">Натисніть «Start» у Telegram. Посилання діє {Math.round(link.expires_in_s / 60)} хв. Чекаємо підтвердження…</p>
          </div>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">Без Telegram Vigil покаже збої лише у вебінтерфейсі. Прив’язка потрібна й для відновлення пароля в наступних версіях.</p>
            <Button className="w-fit" onClick={() => act(async () => setLink(await api<TelegramLink>('/me/telegram', { method: 'POST' })))}>Підключити Telegram</Button>
          </>
        )}
      </section>

      <section className="grid max-w-2xl gap-3 rounded-xl border bg-card p-5 shadow-sm" aria-labelledby="lvl">
        <h2 id="lvl" className="text-lg font-semibold">Які сповіщення надсилати</h2>
        <div role="radiogroup" aria-labelledby="lvl" className="grid gap-2">
          {([['warning', 'Усі: попередження й критичні'], ['critical', 'Лише критичні']] as [Severity, string][]).map(([v, l]) => (
            <label key={v} className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 has-[:checked]:border-primary has-[:checked]:bg-accent">
              <input type="radio" name="sev" checked={u.notify_min_severity === v} onChange={() => act(() => api<Me>('/me', { method: 'PATCH', body: { notify_min_severity: v } }), 'Збережено')} />
              {l}
            </label>
          ))}
        </div>
      </section>
    </>
  )
}
