import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { seedCollectors } from '@/api/fixtures'
import { CollectorManagement } from './collector-management'

const auth = vi.hoisted(() => ({ role: 'administrator' }))
vi.mock('@/features/auth/auth-gate', () => ({ useAuth: () => ({ user: auth }) }))

const source = seedCollectors[0]
const plan = { collectorId: source.id, collectorName: '最新来源名称', sourceUrl: source.sourceUrl, collectionName: source.collectionName, lifecycle: 'active', blockers: [], deleteBlockers: [], historyCounts: { operations: 13, ai_runs: 13, rules: 1, runs: 2, items: 8, sinks: 0, deliveries: 0 }, scheduleEnabled: true, hasHistory: true, planDigest: 'digest1' }
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }) }
function Location() { return <output aria-label="location">{useLocation().pathname}</output> }
function mount(archived = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors']}><CollectorManagement collector={{ ...source, lifecycle: archived ? 'archived' : 'active' }} /><Location /></MemoryRouter></QueryClientProvider>)
  return client
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); auth.role = 'administrator' })
describe('source management', () => {
  it('does not expose management commands to viewers or reviewers', () => {
    auth.role = 'viewer'; mount()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    cleanup(); auth.role = 'reviewer'; mount()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
  it('blocks active work without asking for a name confirmation', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ ...plan, blockers: ['RUN_ALREADY_ACTIVE'], deleteBlockers: ['RUN_ALREADY_ACTIVE'] })))
    const user = userEvent.setup(); mount()
    await user.click(screen.getByRole('button', { name: /管理采集来源/ }))
    expect(screen.getByLabelText('location')).toHaveTextContent('/collectors')
    await user.click(screen.getByRole('menuitem', { name: '删除来源' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('有尚未结束的采集运行')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '删除来源' })).toBeDisabled()
    expect(within(dialog).queryByRole('textbox')).not.toBeInTheDocument()
    expect(within(dialog).getByText('请先停止或等待任务结束；字段迁移须先完成或放弃，然后重新加载预览。')).toBeInTheDocument()
  })
  it('explains retained history and enables deletion after name confirmation', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(plan)))
    const user = userEvent.setup(); mount()
    await user.click(screen.getByRole('button', { name: /管理采集来源/ }))
    await user.click(screen.getByRole('menuitem', { name: '删除来源' }))
    const input = await screen.findByRole('textbox', { name: '输入来源名称确认' })
    expect(screen.getByText('保留的历史')).toBeInTheDocument()
    expect(screen.getByText('已开启的调度将关闭。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '删除来源' })).toBeDisabled()
    await user.type(input, plan.collectorName)
    expect(screen.getByRole('button', { name: '删除来源' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: '重新加载预览' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: '输入来源名称确认' })).toHaveValue(''))
    expect(screen.getByRole('button', { name: '删除来源' })).toBeDisabled()
  })
  it('requires the latest preview name and preserves the idempotency key after a failure', async () => {
    const writes: RequestInit[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url, init?: RequestInit) => {
      if (init?.method === 'POST') { writes.push(init); return writes.length === 1 ? json({ code: 'INTERNAL_ERROR', message: 'retry me', requestId: 'r', retryable: true }, 500) : json({ id: source.id, deleted: true }) }
      return json(plan)
    }))
    const user = userEvent.setup(); const client = mount(); const invalidate = vi.spyOn(client, 'invalidateQueries')
    await user.click(screen.getByRole('button', { name: /管理采集来源/ }))
    await user.click(screen.getByRole('menuitem', { name: '删除来源' }))
    const input = await screen.findByRole('textbox', { name: '输入来源名称确认' })
    await user.type(input, source.name)
    expect(screen.getByRole('button', { name: '删除来源' })).toBeDisabled()
    await user.clear(input); await user.type(input, plan.collectorName)
    await user.click(screen.getByRole('button', { name: '删除来源' }))
    expect(await screen.findByText('retry me')).toBeInTheDocument()
    expect(input).toHaveValue(plan.collectorName)
    await user.click(screen.getByRole('button', { name: '删除来源' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes).toHaveLength(2)
    expect(writes[0].headers).toEqual(writes[1].headers)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['collections'] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['collection'] })
  })
  it('prevents escape, close and repeated submit while archive is pending', async () => {
    let resolve!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(async (_url, init?: RequestInit) => init?.method === 'POST' ? new Promise<Response>(done => { resolve = done }) : json(plan)))
    const user = userEvent.setup(); mount()
    await user.click(screen.getByRole('button', { name: /管理采集来源/ }))
    await user.click(screen.getByRole('menuitem', { name: '归档来源' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '归档来源' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: '归档来源' }))
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '关闭' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消' })).toBeDisabled()
    resolve(json({ ...source, lifecycle: 'archived' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
  it('offers restore rather than edit or reassignment for archived sources', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url, init?: RequestInit) => json(init?.method === 'POST' ? source : { ...plan, lifecycle: 'archived' })))
    const user = userEvent.setup(); mount(true)
    await user.click(screen.getByRole('button', { name: /管理采集来源/ }))
    expect(screen.queryByRole('menuitem', { name: '编辑来源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '调整所属需求' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('menuitem', { name: '恢复来源' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '恢复来源' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: '恢复来源' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
  it('requires every field confirmation and resets them when refreshing a changed preview', async () => {
    const target = { id: 'target', name: '目标标讯', status: 'active' }
    const field = { key: 'title', label: '标题', type: 'string', required: true, identity: false, fingerprint: true, description: '' }
    let digest = 'target1'
    const writes: RequestInit[] = []
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/collections')) return json({ items: [target, { id: source.collectionId, name: '自身', status: 'active' }, { id: 'archived-target', name: '归档目标', status: 'archived' }] })
      if (init?.method === 'POST') { writes.push(init); return json({ ...source, collectionId: 'target', collectionName: target.name }) }
      return json({ ...plan, fromCollectionId: source.collectionId, fromCollectionName: '原需求', targetCollectionId: 'target', targetCollectionName: target.name, targetIntent: '采集标题和正文', targetVersionId: 'target_v2', targetRevision: 2, requiresRecompile: true, historyCounts: { rules: 1, runs: 2, items: 8, sinks: 1, deliveries: 2 }, unresolvedHistory: [], changes: [{ key: 'title', kind: 'changed', before: field, after: { ...field, description: '目标标题' } }, { key: 'content', kind: 'added', before: null, after: { ...field, key: 'content', label: '正文' } }], planDigest: digest })
    })
    vi.stubGlobal('fetch', fetcher)
    const user = userEvent.setup(); mount()
    await user.click(screen.getByRole('button', { name: /管理采集来源/ }))
    await user.click(screen.getByRole('menuitem', { name: '调整所属需求' }))
    const select = await screen.findByRole('combobox', { name: '目标需求' })
    await waitFor(() => expect(select).toBeEnabled())
    expect(screen.queryByRole('option', { name: '自身' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '归档目标' })).not.toBeInTheDocument()
    await user.selectOptions(select, 'target')
    await screen.findByText('target_v2')
    const submit = screen.getByRole('button', { name: '调整所属需求' })
    expect(submit).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /title/ }))
    expect(submit).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /content/ }))
    expect(submit).toBeEnabled()
    digest = 'target2'
    await user.click(screen.getByRole('button', { name: '重新加载预览' }))
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /title/ })).not.toBeChecked())
    expect(submit).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /title/ }))
    await user.click(screen.getByRole('checkbox', { name: /content/ }))
    await user.click(submit)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(JSON.parse(String(writes[0].body))).toEqual({ targetCollectionId: 'target', planDigest: 'target2', confirmedChanges: ['title', 'content'] })
  })
  it('shows preview failures and allows a real reload instead of a simulated success', async () => {
    let failing = true
    vi.stubGlobal('fetch', vi.fn(async () => failing ? json({ code: 'UNAVAILABLE', message: 'preview offline', requestId: 'r', retryable: true }, 503) : json(plan)))
    const user = userEvent.setup(); mount()
    await user.click(screen.getByRole('button', { name: /管理采集来源/ }))
    await user.click(screen.getByRole('menuitem', { name: '归档来源' }))
    expect(await screen.findByText('preview offline')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '归档来源' })).toBeDisabled()
    failing = false
    await user.click(screen.getByRole('button', { name: '重新加载预览' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '归档来源' })).toBeEnabled())
  })
})
