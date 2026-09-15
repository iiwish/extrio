import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { CollectionField, FieldSuggestion, CollectionMigrationPlan } from '@/api/types'
import { api, ApiRequestError } from '@/api/client'
import { CollectionFieldTools } from './collection-field-tools'
import { CollectionMigration } from './collection-migration'
import { CollectionFields } from './collection-fields'
import { requirement } from './collection-test-data'
import { MemoryRouter } from 'react-router-dom'

const title: CollectionField = { key: 'title', label: '标题', type: 'string', required: true, identity: true, fingerprint: true, description: '' }
const amount: CollectionField = { ...title, key: 'amount', label: '金额', type: 'number', identity: false }
const data = requirement({ fieldDraft: { fields: [title] } })
const suggestion: FieldSuggestion = { id: 'suggestion_test', collectionId: data.id, baseRevision: 1, status: 'succeeded', fields: [title, amount], error: null, attempt: 1, createdAt: '2026-09-10T08:00:00Z', finishedAt: '2026-09-10T08:01:00Z', appliedAt: null, modelInvocations: [] }
const plan: CollectionMigrationPlan = { collectorId: data.sources[0].id, fromVersionId: 'tender_notice_v4', targetVersionId: 'colver_target', targetVersionNumber: 1, changes: [{ key: 'amount', kind: 'added', before: null, after: amount, breaking: true }], blockers: [], requiresRecompile: true, planDigest: 'sha256:plan' }
function wrapper({ children }: { children: React.ReactNode }) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider> }
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('recovers a saved suggestion and applies only explicitly selected fields', async () => {
  vi.spyOn(api, 'fieldSuggestions').mockResolvedValue([suggestion])
  const apply = vi.spyOn(api, 'applyFieldSuggestion').mockResolvedValue(data)
  render(<CollectionFieldTools requirement={data} disabled={false} />, { wrapper })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '字段工具' }))
  await user.click(screen.getByRole('menuitem', { name: 'AI 字段建议' }))
  const accept = await screen.findByRole('button', { name: '接受所选字段' })
  expect(accept).toBeDisabled()
  await user.click(await screen.findByRole('checkbox', { name: '确认 amount' }))
  await user.click(accept)
  await waitFor(() => expect(apply).toHaveBeenCalledWith(data.id, suggestion.id, { revision: 1, selectedKeys: ['amount'] }))
})

it('does not apply stale suggestions or start another task while one is active', async () => {
  vi.spyOn(api, 'fieldSuggestions').mockResolvedValue([{ ...suggestion, baseRevision: 0 }])
  const view = render(<CollectionFieldTools requirement={data} disabled={false} />, { wrapper })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '字段工具' }))
  await user.click(screen.getByRole('menuitem', { name: 'AI 字段建议' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('此建议已过期')
  expect(screen.getByRole('button', { name: '接受所选字段' })).toBeDisabled()
  view.unmount()
  vi.mocked(api.fieldSuggestions).mockResolvedValue([{ ...suggestion, status: 'running', fields: [] }])
  render(<CollectionFieldTools requirement={data} disabled={false} />, { wrapper })
  await user.click(screen.getByRole('button', { name: '字段工具' }))
  await user.click(screen.getByRole('menuitem', { name: 'AI 字段建议' }))
  expect(await screen.findByRole('button', { name: '重新生成建议' })).toBeDisabled()
})

it('retains selected fields after a failed apply and permits a fresh task after generation failure', async () => {
  vi.spyOn(api, 'fieldSuggestions').mockResolvedValue([suggestion])
  vi.spyOn(api, 'applyFieldSuggestion').mockRejectedValue(new Error('offline'))
  render(<CollectionFieldTools requirement={data} disabled={false} />, { wrapper })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '字段工具' }))
  await user.click(screen.getByRole('menuitem', { name: 'AI 字段建议' }))
  await user.click(await screen.findByRole('checkbox', { name: '确认 amount' }))
  await user.click(screen.getByRole('button', { name: '接受所选字段' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  expect(screen.getByRole('checkbox', { name: '确认 amount' })).toBeChecked()
  expect(screen.getByRole('button', { name: '重新生成建议' })).toBeEnabled()
})

it('requires all migration changes to be reviewed and sends the fixed target and digest', async () => {
  vi.spyOn(api, 'collectionMigrationPlan').mockResolvedValue(plan)
  const migrate = vi.spyOn(api, 'migrateCollectionVersion').mockResolvedValue(data.sources[0] as Awaited<ReturnType<typeof api.migrateCollectionVersion>>)
  render(<CollectionMigration source={data.sources[0]} targetVersionId={plan.targetVersionId} canReview />, { wrapper })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '迁移字段版本' }))
  const confirm = await screen.findByRole('button', { name: '确认并准备重编译' })
  expect(confirm).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: '确认 amount' }))
  await user.click(confirm)
  await waitFor(() => expect(migrate).toHaveBeenCalledWith(plan.collectorId, { targetVersionId: plan.targetVersionId, planDigest: plan.planDigest, confirmedChanges: ['amount'] }))
})

it('keeps migration confirmation open while its command is pending', async () => {
  vi.spyOn(api, 'collectionMigrationPlan').mockResolvedValue(plan)
  let finish!: (value: Awaited<ReturnType<typeof api.migrateCollectionVersion>>) => void
  vi.spyOn(api, 'migrateCollectionVersion').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  render(<CollectionMigration source={data.sources[0]} targetVersionId={plan.targetVersionId} canReview />, { wrapper })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '迁移字段版本' }))
  await user.click(await screen.findByRole('checkbox', { name: '确认 amount' }))
  await user.click(screen.getByRole('button', { name: '确认并准备重编译' }))
  await user.keyboard('{Escape}')
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '取消' })).toBeDisabled()
  finish(data.sources[0] as Awaited<ReturnType<typeof api.migrateCollectionVersion>>)
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it('blocks migration during a run and hides migration commands for non-reviewers', async () => {
  vi.spyOn(api, 'collectionMigrationPlan').mockResolvedValue({ ...plan, blockers: ['RUN_ALREADY_ACTIVE'] })
  const user = userEvent.setup()
  const view = render(<CollectionMigration source={data.sources[0]} targetVersionId={plan.targetVersionId} canReview />, { wrapper })
  await user.click(screen.getByRole('button', { name: '迁移字段版本' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('采集运行尚未结束')
  await user.click(screen.getByRole('checkbox', { name: '确认 amount' }))
  expect(screen.getByRole('button', { name: '确认并准备重编译' })).toBeDisabled()
  view.unmount()
  render(<CollectionMigration source={data.sources[0]} targetVersionId={plan.targetVersionId} canReview={false} />, { wrapper })
  expect(screen.queryByRole('button', { name: '迁移字段版本' })).not.toBeInTheDocument()
})

it('abandons a failed migration only after explicit confirmation', async () => {
  const cancel = vi.spyOn(api, 'cancelCollectionMigration').mockResolvedValue(data.sources[0] as Awaited<ReturnType<typeof api.cancelCollectionMigration>>)
  render(<CollectionMigration source={{ ...data.sources[0], activeOperationId: null, pendingCollectionVersion: plan.targetVersionId, collectionMigration: { fromVersionId: plan.fromVersionId, targetVersionId: plan.targetVersionId, targetVersionNumber: 1, status: 'failed', startedAt: suggestion.createdAt } }} canReview />, { wrapper })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '放弃迁移' }))
  expect(cancel).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '确认放弃迁移' }))
  await waitFor(() => expect(cancel).toHaveBeenCalledWith(data.sources[0].id, { targetVersionId: plan.targetVersionId }))
})

it('captures publication revision and retains its dialog on conflict', async () => {
  const publish = vi.spyOn(api, 'publishCollectionVersion').mockRejectedValue(new ApiRequestError({ code: 'COLLECTION_CONFLICT', message: 'conflict', requestId: 'test', retryable: false }))
  const client = new QueryClient()
  const ui = (revision: number) => <QueryClientProvider client={client}><MemoryRouter><CollectionFields requirement={{ ...data, revision }} canEdit={false} canPublish /></MemoryRouter></QueryClientProvider>
  const view = render(ui(1))
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '发布字段版本' }))
  view.rerender(ui(2))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '发布字段版本' }))
  expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('conflict')
  expect(publish).toHaveBeenCalledWith(data.id, { revision: 1, note: undefined })
})
