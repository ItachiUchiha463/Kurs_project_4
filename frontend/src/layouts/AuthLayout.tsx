import { Navigate, Outlet } from 'react-router-dom'

import { ThemeToggle } from '@/components/small'
import { getToken } from '@/lib/auth'
import { Logo } from '@/layouts/AppLayout'

export function AuthLayout() {
  if (getToken()) return <Navigate to="/" replace />
  return (
    <div className="grid min-h-screen place-items-center p-4">
      <div className="absolute right-4 top-4"><ThemeToggle /></div>
      <main id="main-content" className="w-full max-w-md rounded-xl border bg-card p-6 shadow-sm">
        <div className="mb-5"><Logo /></div>
        <Outlet />
      </main>
    </div>
  )
}
