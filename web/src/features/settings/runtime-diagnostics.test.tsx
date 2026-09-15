import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { RuntimeDiagnosticsSection } from './runtime-diagnostics'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('shows deployment mismatch and real queue counts without exposing paths', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ready: false, reason: 'worker_deployment_mismatch', liveWorkers: 1, mismatchedWorkers: 1, workers: [{ id: 'worker_test', deploymentMatches: false, lastSeen: '2026-09-10T00:00:00Z' }], queue: { queuedJobs: 3, runningJobs: 1, oldestDueSeconds: 42 }, heartbeatMaxAgeSeconds: 20, checkedAt: '2026-09-10T00:00:00Z' }), { headers: { 'Content-Type': 'application/json' } })))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RuntimeDiagnosticsSection /></QueryClientProvider>)
  expect(await screen.findByText('Worker 部署不一致')).toBeInTheDocument()
  expect(screen.getByText('worker_test')).toBeInTheDocument()
  expect(screen.getByText('42 秒')).toBeInTheDocument()
})
