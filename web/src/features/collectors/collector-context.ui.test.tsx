import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { CollectorPage } from './collector-page'
import type { CollectorDetail } from '@/api/types'

const authUser = vi.hoisted(() => ({role: 'viewer', displayName: 'G4 Real Reviewer', username: 'g4-reviewer'}))
vi.mock('@/features/auth/auth-gate', () => ({useAuth: () => ({user: authUser})}))
afterEach(() => {cleanup(); vi.restoreAllMocks(); authUser.role = 'viewer'})

function renderConfiguration(source: CollectorDetail, edit = false) {
  vi.spyOn(api, 'collector').mockResolvedValue(source)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  vi.spyOn(api, 'sinks').mockResolvedValue([])
  vi.spyOn(api, 'deliveries').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/collectors/${source.id}?section=config${edit ? '&edit=definition' : ''}`]}><Routes><Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
}

it('keeps definition input and retry key after a failure and prevents closing a pending save', async () => {
  authUser.role = 'engineer'
  const source = { ...seedCollectors[0], managementRevision: 4 }
  let reject!: (reason: Error) => void
  const save = vi.spyOn(api, 'updateCollector').mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail })).mockResolvedValue({ ...source, name: '改名来源', managementRevision: 5 })
  renderConfiguration(source, true)
  const user = userEvent.setup()
  const dialog = await screen.findByRole('dialog')
  const input = within(dialog).getByRole('textbox', { name: '采集来源名称' })
  await user.clear(input); await user.type(input, '改名来源')
  await user.click(within(dialog).getByRole('button', { name: '保存信息' }))
  expect(input).toBeDisabled()
  await user.keyboard('{Escape}')
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(within(dialog).queryByRole('button', { name: '关闭' })).not.toBeInTheDocument()
  reject(new Error('definition offline'))
  expect(await within(dialog).findByText('definition offline')).toBeInTheDocument()
  expect(input).toHaveValue('改名来源')
  await user.click(within(dialog).getByRole('button', { name: '保存信息' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(save).toHaveBeenCalledTimes(2)
  expect(save.mock.calls[0][1]).toMatchObject({ name: '改名来源', managementRevision: 4 })
  expect(save.mock.calls[0][2]).toBe(save.mock.calls[1][2])
})

it('keeps archived evidence readable without execution or definition mutation controls', async () => {
  authUser.role = 'administrator'
  renderConfiguration({ ...seedCollectors[0], lifecycle: 'archived' })
  expect(await screen.findByText('此来源已归档，调度与执行已停用；历史记录仍可查看。')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '审核并发布' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '立即运行' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '编辑' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '重新生成' })).toBeDisabled()
})

it('keeps targeted warning repair unavailable to read-only roles', async () => {
  renderConfiguration({ ...seedCollectors[0], status: 'ready_review' })
  const user = userEvent.setup()
  await user.click(await screen.findByRole('tab', { name: /规则审核/ }))
  expect(await screen.findByRole('button', { name: '让 AI 修复字段 budget' })).toBeDisabled()
})

it('identifies the authenticated reviewer in the publish confirmation', async () => {
  authUser.role = 'administrator'
  const collector = {...seedCollectors[0], status: 'ready_review' as const}
  collector.candidate = {...collector.candidate!, fields: collector.candidate!.fields.map(field => ({...field, warning: null}))}
  vi.spyOn(api, 'collector').mockResolvedValue(collector)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?section=rule']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  await userEvent.setup().click(await screen.findByRole('button', {name: '审核并发布'}))
  expect(await screen.findByRole('dialog')).toHaveTextContent('G4 Real Reviewer')
  expect(screen.getByRole('dialog')).not.toHaveTextContent('林然')
})

it('counts actual preview records for single-page validation samples', async () => {
  const collector = {...seedCollectors[0], status: 'ready_review' as const}
  collector.candidate = {...collector.candidate!, mode: 'single', discovery: {...collector.candidate!.discovery, detailPagesValidated: 0}}
  vi.spyOn(api, 'collector').mockResolvedValue(collector)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?section=rule']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  const label = await screen.findByText('验证样本', {selector: '.review-summary-strip small'})
  expect(label.parentElement?.querySelector('strong')).toHaveTextContent(String(collector.previewItems.length))
  expect(label.parentElement?.querySelector('strong')?.textContent).not.toContain('/')
})

it('shows abnormal latest-run state without offering a read-only user execution controls', async () => {
  const collector = {...seedCollectors[0],status:'published' as const,latestRunId:'last'}
  vi.spyOn(api,'collector').mockResolvedValue(collector)
  vi.spyOn(api,'runDetail').mockResolvedValue({...seedRuns[0],id:'last',status:'partially_succeeded',summary:'详情抓取不完整'})
  vi.spyOn(api,'aiRuns').mockResolvedValue([])
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?returnTo=%2Fruns%3Fview%3Dai']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('heading',{name:'最近运行需要处理'})).toBeInTheDocument()
  expect(screen.getByRole('button',{name:'立即运行'})).toBeDisabled()
  await userEvent.setup().click(screen.getByRole('tab',{name:'采集配置'}))
  expect(screen.getByRole('button',{name:'编辑'})).toBeDisabled()
})

it('does not present candidate samples as latest-run results when that run fails to load', async () => {
  vi.spyOn(api, 'collector').mockResolvedValue({ ...seedCollectors[0], status: 'published', latestRunId: 'unavailable' })
  vi.spyOn(api, 'runDetail').mockRejectedValue(new Error('Run temporarily unavailable'))
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('alert')).toHaveTextContent('Run temporarily unavailable')
  expect(screen.getByRole('heading', {name:'最近运行结果不可用'})).toBeInTheDocument()
  expect(screen.queryByRole('heading', {name:'最近采集结果'})).not.toBeInTheDocument()
  expect(screen.queryByText(/watermark/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', {name:'查看完整 Run'})).toBeEnabled()
})

it('uses run counters rather than the number of preview items for latest-run totals', async () => {
  vi.spyOn(api, 'collector').mockResolvedValue({ ...seedCollectors[0], status: 'published', latestRunId: 'last' })
  vi.spyOn(api, 'runDetail').mockResolvedValue({ ...seedRuns[0], id: 'last', acceptedCount: 205, rejectedCount: 23, items: [] })
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('205 接收 · 23 拒绝')).toBeInTheDocument()
})

it('displays contract coverage and missing requirement fields gap in review workspace', async () => {
  const collector = {
    ...seedCollectors[0],
    status: 'ready_review' as const,
    collectionFields: [
      { key: 'title', label: '标题', type: 'string' as const, required: true, identity: false, fingerprint: true, description: '' },
      { key: 'buyer', label: '采购单位', type: 'string' as const, required: true, identity: false, fingerprint: true, description: '' },
      { key: 'optionalMissing', label: '缺失选填字段', type: 'number' as const, required: false, identity: false, fingerprint: true, description: '' },
      { key: 'requiredMissing', label: '缺失必填字段', type: 'string' as const, required: true, identity: false, fingerprint: true, description: '' },
    ],
  }
  vi.spyOn(api, 'collector').mockResolvedValue(collector)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/collectors/source?section=rule']}>
        <Routes>
          <Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}>
            <Route path="/collectors/:collectorId" element={<CollectorPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
  expect(await screen.findByText(/1 个必填需求字段缺失/)).toBeInTheDocument()
  expect(screen.getByText('需求未覆盖字段（契约缺口）')).toBeInTheDocument()
  expect(screen.getByText('缺失选填字段')).toBeInTheDocument()
  expect(screen.getAllByText('缺失必填字段')).toHaveLength(2)
  expect(screen.getByText('安全 (选填缺口)')).toBeInTheDocument()
  expect(screen.getByText('阻断 (必填缺失)')).toBeInTheDocument()
})
