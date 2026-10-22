import { EmptyState, LinkButton, PageHead } from '@/components/small'

export function NotFoundPage() {
  document.title = 'Сторінку не знайдено – Vigil'
  return (
    <>
      <PageHead title="Сторінку не знайдено" />
      <EmptyState title="Такої адреси немає" action={<LinkButton to="/">На дашборд</LinkButton>}>
        Можливо, об’єкт чи інцидент видалено або посилання застаріло.
      </EmptyState>
    </>
  )
}
