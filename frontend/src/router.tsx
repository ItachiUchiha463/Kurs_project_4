import { createBrowserRouter } from 'react-router-dom'

import { AuthLayout } from '@/layouts/AuthLayout'
import { RequireAuth } from '@/layouts/AppLayout'
import { AddServerPage } from '@/pages/AddServer'
import { DashboardPage } from '@/pages/Dashboard'
import { IncidentPage } from '@/pages/Incident'
import { IncidentsPage } from '@/pages/Incidents'
import { LoginPage, RegisterPage } from '@/pages/Auth'
import { NotFoundPage } from '@/pages/NotFound'
import { ProfilePage } from '@/pages/Profile'
import { TargetPage } from '@/pages/Target'

export const router = createBrowserRouter([
  { element: <AuthLayout />, children: [{ path: '/login', element: <LoginPage /> }, { path: '/register', element: <RegisterPage /> }] },
  {
    element: <RequireAuth />,
    children: [
      { path: '/', element: <DashboardPage /> },
      { path: '/targets/new', element: <AddServerPage /> },
      { path: '/targets/:id', element: <TargetPage /> },
      { path: '/incidents', element: <IncidentsPage /> },
      { path: '/incidents/:id', element: <IncidentPage /> },
      { path: '/profile', element: <ProfilePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
