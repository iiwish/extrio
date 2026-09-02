import { Navigate, createBrowserRouter } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Skeleton } from '@/components/ui/skeleton'
import { AppShell } from './app-shell'
import { AuthGate } from '@/features/auth/auth-gate'

function RouteFallback() {
  const { t } = useTranslation('common')
  return <div className="page-frame" aria-label={t('aria.pageLoading')}><Skeleton className="h-8 w-56" /><Skeleton className="mt-5 h-36 w-full" /></div>
}

export const router = createBrowserRouter([
  {
    element: <AuthGate><AppShell /></AuthGate>,
    HydrateFallback: RouteFallback,
    children: [
      {
        index: true,
        lazy: async () => ({ Component: (await import('@/features/home/home-page')).HomePage }),
      },
      {
        path: '/collectors',
        lazy: async () => ({ Component: (await import('@/features/collectors/collectors-page')).CollectorsPage }),
      },
      {
        path: '/collectors/new',
        lazy: async () => ({ Component: (await import('@/features/collectors/new-collector-page')).NewCollectorPage }),
      },
      {
        path: '/collectors/:collectorId',
        lazy: async () => ({ Component: (await import('@/features/collectors/collector-page')).CollectorPage }),
      },
      {
        path: '/runs',
        lazy: async () => ({ Component: (await import('@/features/runs/runs-page')).RunsPage }),
      },
      {
        path: '/runs/:runId',
        lazy: async () => ({ Component: (await import('@/features/runs/run-page')).RunPage }),
      },
      {
        path: '/ai-runs/:aiRunId',
        lazy: async () => ({ Component: (await import('@/features/runs/ai-run-page')).AiRunPage }),
      },
      {
        path: '/items',
        lazy: async () => ({ Component: (await import('@/features/items/items-page')).ItemsPage }),
      },
      {
        path: '/items/:itemId',
        lazy: async () => ({ Component: (await import('@/features/items/item-page')).ItemPage }),
      },
      {
        path: '/settings',
        lazy: async () => ({ Component: (await import('@/features/settings/model-settings-page')).ModelSettingsPage }),
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
