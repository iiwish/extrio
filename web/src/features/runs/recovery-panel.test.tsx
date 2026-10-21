import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { RecoveryPanel } from './recovery-panel'
import { api } from '@/api/client'
import type { RecoveryBatch } from '@/api/types'

vi.mock('@/features/auth/auth-gate', () => ({ useAuth: () => ({ user: { role: 'engineer' } }) }))
const batch: RecoveryBatch = { id: 'recovery-1', collectorId: 'collector-1', seedRunId: 'seed-1', status: 'cooling_down',
  reason: 'source_rate_limited', createdAt: '2026-10-20T01:00:00Z', updatedAt: '2026-10-20T01:00:00Z',
  expiresAt: '2026-10-21T01:00:00Z', finishedAt: null, nextAttemptAt: '2026-10-20T03:00:00Z', maxAttempts: 3,
  attemptRunIds: ['run-retry-1'], activeRunId: null, reservedRequests: 120, maxRequests: 360, requestsPerAttempt: 120,
  maxPages: 3, maxItems: 50, cooldownSeconds: [1800, 7200, 21600], windowStart: '2026-09-19',
  ruleVersion: 'rule-v6', policyVersion: 'policy-v5', cancelRequested: false, resumePage: 99 }

function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><RecoveryPanel runId="seed-1" eligible /></MemoryRouter>
  </QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('shows durable cooldown and attempt links without rewriting the run as successful', async () => {
  vi.spyOn(api, 'runRecovery').mockResolvedValue(batch)
  show()
  expect(await screen.findByText('冷却中')).toBeInTheDocument()
  expect(screen.getByText('1 / 3')).toBeInTheDocument()
  expect(screen.getByText('120 / 360')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '恢复运行 1' })).toHaveAttribute('href', '/runs/run-retry-1?section=scope')
  expect(screen.queryByText('本次窗口已覆盖')).not.toBeInTheDocument()
})

it('cancels explicitly and does not offer an automatic fresh budget', async () => {
  vi.spyOn(api, 'runRecovery').mockResolvedValue({ ...batch, status: 'cancelled' })
    .mockResolvedValueOnce(batch)
  const cancel = vi.spyOn(api, 'cancelRecovery').mockResolvedValue({ ...batch, status: 'cancelled' })
  show()
  await userEvent.click(await screen.findByRole('button', { name: '停止恢复' }))
  expect(cancel).toHaveBeenCalledWith(batch.id)
  expect(await screen.findByText('已停止')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '创建有限恢复批次' })).not.toBeInTheDocument()
})

it('labels verified continuation separately from completed coverage', async () => {
  vi.spyOn(api, 'runRecovery').mockResolvedValue({ ...batch, status: 'recovered', reason: 'continuation_verified' })
  show()
  expect(await screen.findByText('接续已验证')).toBeInTheDocument()
  expect(screen.getByText('有界续跑进度已验证')).toBeInTheDocument()
  expect(screen.queryByText('本次窗口已覆盖')).not.toBeInTheDocument()
})

it('does not turn a failed read into an empty batch or a start action', async () => {
  vi.spyOn(api, 'runRecovery').mockRejectedValue(new Error('unavailable'))
  show()
  expect(await screen.findByText('unavailable')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '创建有限恢复批次' })).not.toBeInTheDocument()
})
