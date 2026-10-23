import { createBrowserRouter } from 'react-router-dom'

import { AuthLayout } from '@/layouts/AuthLayout'
import { RequireAuth } from '@/layouts/AppLayout'
import { AddServerPage } from '@/pages/AddServer'
import { DashboardPage } from '@/pages/Dashboard'
import { IncidentsPage } from '@/pages/Incidents'
import { LoginPage, RegisterPage } from '@/pages/Auth'
import { NotFoundPage } from '@/pages/NotFound'
import { ProfilePage } from '@/pages/Profile'

export const router = createBrowserRouter([
  { element: <AuthLayout />, children: [{ path: '/login', element: <LoginPage /> }, { path: '/register', element: <RegisterPage /> }] },
  {
    element: <RequireAuth />,
    children: [
      { path: '/', element: <DashboardPage /> },
      { path: '/targets/new', element: <AddServerPage /> },
      { path: '/targets/:id', lazy: async () => ({ Component: (await import('@/pages/Target')).TargetPage }) },
      { path: '/incidents', element: <IncidentsPage /> },
      { path: '/incidents/:id', lazy: async () => ({ Component: (await import('@/pages/Incident')).IncidentPage }) },
      { path: '/profile', element: <ProfilePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
