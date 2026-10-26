import { Activity, FileBarChart, LayoutDashboard, LogOut, Menu, Settings, TriangleAlert, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { LiveIndicator, ThemeToggle } from '@/components/small'
import { Button } from '@/components/ui/button'
import { clearToken, getToken } from '@/lib/auth'
import { useIncidents, useMe } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useLive } from '@/ws/live'
import { useQueryClient } from '@tanstack/react-query'

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 font-semibold">
      <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
        <Activity className="size-5" aria-hidden="true" />
      </span>
      Vigil
    </Link>
  )
}

/** Усі сторінки після входу: без токена – на /login із поверненням назад (ТЗ 11.1). */
export function RequireAuth() {
  const location = useLocation()
  if (!getToken()) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return <AppLayout />
}

function AppLayout() {
  useLive()
  const [menu, setMenu] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const me = useMe()
  const active = useIncidents({ status: 'active' })
  const count = active.data?.length ?? 0

  // після переходу фокус на заголовок нової сторінки: програма читання з екрана оголошує, де користувач
  useEffect(() => {
    setMenu(false)
    const h1 = document.querySelector<HTMLElement>('main h1')
    if (h1) {
      h1.tabIndex = -1
      h1.focus({ preventScroll: true })
    }
    window.scrollTo(0, 0)
  }, [location.pathname])

  const logout = () => {
    clearToken()
    qc.clear()
    navigate('/login')
  }

  const link = ({ isActive }: { isActive: boolean }) =>
    cn('flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors hover:bg-accent',
      isActive ? 'bg-accent text-accent-foreground' : 'text-foreground')

  return (
    <div className="mx-auto grid min-h-screen max-w-[1480px] md:grid-cols-[232px_minmax(0,1fr)] md:gap-5 md:px-4">
      <button
        className="absolute left-4 top-[-80px] z-50 rounded-lg bg-primary px-3 py-2 font-semibold text-primary-foreground focus:top-3"
        onClick={() => document.getElementById('main-content')?.focus()}
      >
        Перейти до вмісту
      </button>

      <header className="flex items-center justify-between border-b bg-background p-3 md:hidden">
        <Logo />
        <Button variant="outline" size="icon" onClick={() => setMenu((m) => !m)} aria-label="Меню" aria-expanded={menu}>
          <Menu aria-hidden="true" />
        </Button>
      </header>

      <nav aria-label="Головне меню" className={cn('flex-col gap-1 p-3 md:sticky md:top-4 md:flex md:h-fit md:p-0 md:py-4', menu ? 'flex' : 'hidden')}>
        <div className="mb-4 hidden px-3 md:block"><Logo /></div>
        <NavLink to="/" end className={link}><LayoutDashboard className="size-5" aria-hidden="true" />Дашборд</NavLink>
        <NavLink to="/incidents" className={link}>
          <TriangleAlert className="size-5" aria-hidden="true" />Інциденти
          {count > 0 && (
            <span className="ml-auto rounded-full bg-crit px-2 py-0.5 text-xs font-bold text-white" aria-label={`${count} активних`}>{count}</span>
          )}
        </NavLink>
        <NavLink to="/reports" className={link}><FileBarChart className="size-5" aria-hidden="true" />Звіти</NavLink>
        <NavLink to="/settings" className={link}><Settings className="size-5" aria-hidden="true" />Налаштування</NavLink>
        <NavLink to="/profile" className={link}><UserRound className="size-5" aria-hidden="true" />Профіль</NavLink>
        <Button variant="ghost" className="mt-2 justify-start gap-3 px-3 text-muted-foreground" onClick={logout}>
          <LogOut aria-hidden="true" />Вийти
        </Button>
      </nav>

      <div className="flex min-w-0 flex-col gap-5 p-4 md:px-0">
        <div className="flex items-center justify-end gap-3">
          <LiveIndicator />
          <ThemeToggle />
          <span className="grid size-9 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-foreground" title={me.data?.email}>
            {me.data?.full_name.slice(0, 2).toUpperCase() ?? '…'}
          </span>
        </div>
        <main id="main-content" tabIndex={-1} className="flex min-w-0 flex-col gap-5 outline-none">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
