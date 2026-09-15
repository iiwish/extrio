import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { CollectorPage } from './collector-page'
import type { CollectorDetail } from '@/api/types'
import i18next, { createInstance } from 'i18next'
import { I18nextProvider, setI18n } from 'react-i18next'
import { initI18n } from '@/i18n'

const authUser = vi.hoisted(() => ({role: 'viewer', displayName: 'G4 Real Reviewer', username: 'g4-reviewer'}))
vi.mock('@/features/auth/auth-gate', () => ({useAuth: () => ({user: authUser})}))
afterEach(() => {cleanup(); setI18n(i18next); vi.restoreAllMocks(); authUser.role = 'viewer'})

function renderConfiguration(source: CollectorDetail, edit = false, section: string = 'config') {
  vi.spyOn(api, 'collector').mockResolvedValue(source)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  vi.spyOn(api, 'sinks').mockResolvedValue([])
  vi.spyOn(api, 'deliveries').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/collectors/${source.id}?${section ? `section=${section}` : ''}${edit ? '&edit=definition' : ''}`]}><Routes><Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
}

it.each(['published', 'ready_review'] as const)('selects the appropriate default task for $0 sources', async status => {
  renderConfiguration({ ...seedCollectors[0], status, latestRunId: null }, false, '')
  expect(await screen.findByRole('tab', { name: status === 'ready_review' ? /规则审核/ : '采集配置' })).toHaveAttribute('data-state', 'active')
})

it('keeps evidence export reachable when there is no rule tab', async () => {
  renderConfiguration({ ...seedCollectors[0], status: 'draft', candidate: null, activeRuleVersion: null }, false, 'rule')
  expect(await screen.findByRole('tab', { name: '采集配置' })).toHaveAttribute('data-state', 'active')
  expect(screen.getByRole('button', { name: /签名证据包/ })).toBeInTheDocument()
})

it('puts the full entry URL before the intent and keeps technical rules out of the configuration task', async () => {
  const source = { ...seedCollectors[0], sourceUrl: 'https://example.com/notices/2026/list?region=beijing&category=construction' }
  renderConfiguration(source)
  const panel = await screen.findByRole('region', { name: '采集入口配置' })
  expect(within(panel).getByText(source.sourceUrl)).toBeInTheDocument()
  expect(within(panel).getByRole('link', { name: '打开采集入口' })).toHaveAttribute('href', source.sourceUrl)
  expect(within(panel).getByText(source.sourceUrl).compareDocumentPosition(within(panel).getByText(source.intent)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.queryByText(source.candidate!.listSelector)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '编辑' })).toBeDisabled()
})

it('copies the exact URL with success feedback without changing the source', async () => {
  const user = userEvent.setup()
  const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  const save = vi.spyOn(api, 'updateCollector')
  renderConfiguration(seedCollectors[0])
  await user.click(await screen.findByRole('button', { name: '复制采集入口 URL' }))
  expect(copy).toHaveBeenCalledWith(seedCollectors[0].sourceUrl)
  expect(await screen.findByRole('status')).toHaveTextContent('URL 已复制')
  expect(save).not.toHaveBeenCalled()
})

it('reports clipboard failure without claiming success', async () => {
  const user = userEvent.setup()
  vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Permission denied'))
  renderConfiguration(seedCollectors[0])
  await user.click(await screen.findByRole('button', { name: '复制采集入口 URL' }))
  expect(await screen.findByRole('status')).toHaveTextContent('复制失败')
  expect(screen.getByRole('status')).not.toHaveTextContent('URL 已复制')
})

it('warns about URL changes and cancels without saving or generating rules', async () => {
  authUser.role = 'engineer'
  const save = vi.spyOn(api, 'updateCollector')
  const generate = vi.spyOn(api, 'startExploration')
  const user = userEvent.setup()
  renderConfiguration(seedCollectors[0], true)
  const dialog = await screen.findByRole('dialog')
  const input = within(dialog).getByRole('textbox', { name: '入口网址' })
  expect(within(dialog).getAllByRole('textbox')[0]).toBe(input)
  await user.clear(input)
  await user.type(input, 'https://example.com/notices?region=beijing')
  expect(within(dialog).getByRole('alert')).toHaveTextContent('保存后关闭调度')
  expect(within(dialog).getByRole('button', { name: '仅保存定义' })).toBeEnabled()
  await user.click(within(dialog).getByRole('button', { name: '取消' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(save).not.toHaveBeenCalled()
  expect(generate).not.toHaveBeenCalled()
  expect(screen.getByText(seedCollectors[0].sourceUrl)).toBeInTheDocument()
})

it('saves an edited URL with its revision without implicitly generating rules', async () => {
  authUser.role = 'engineer'
  const source = { ...seedCollectors[0], managementRevision: 4 }
  const sourceUrl = 'https://example.com/notices?region=beijing'
  const save = vi.spyOn(api, 'updateCollector').mockResolvedValue({ ...source, sourceUrl, managementRevision: 5 })
  const generate = vi.spyOn(api, 'startExploration')
  const user = userEvent.setup()
  renderConfiguration(source, true)
  const dialog = await screen.findByRole('dialog')
  const input = within(dialog).getByRole('textbox', { name: '入口网址' })
  await user.clear(input)
  await user.type(input, sourceUrl)
  await user.click(within(dialog).getByRole('button', { name: '仅保存定义' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(save).toHaveBeenCalledWith(source.id, expect.objectContaining({ sourceUrl, managementRevision: 4 }), expect.any(String))
  expect(generate).not.toHaveBeenCalled()
  expect(screen.getByText(sourceUrl)).toBeInTheDocument()
})

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
  await userEvent.setup().click(screen.getByRole('tab', { name: /规则/ }))
  expect(screen.getByRole('heading', { name: '规则工作区' })).toBeVisible()
  expect(screen.queryByText('规则工作区', { selector: 'summary' })).not.toBeInTheDocument()
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
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?section=overview&returnTo=%2Fruns%3Fview%3Dai']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
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
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?section=overview']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
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
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?section=overview']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('205 接收 · 23 拒绝')).toBeInTheDocument()
})

it.each([{ enabled: false, language: 'zh' }, { enabled: true, language: 'zh' }, { enabled: true, language: 'en' }])('shows actual scheduling on the overview ($language, enabled=$enabled) without granting write access', async ({ enabled, language }) => {
  const instance = initI18n(createInstance())
  await instance.changeLanguage(language)
  const collector = { ...seedCollectors[0], status: 'published' as const, latestRunId: null, schedule: { ...seedCollectors[0].schedule, enabled, nextRunAt: enabled ? '2026-09-15T08:00:00Z' : null } }
  vi.spyOn(api, 'collector').mockResolvedValue(collector)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<I18nextProvider i18n={instance}><QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?section=overview']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider></I18nextProvider>)
  const summary = await screen.findByRole('region', { name: language === 'en' ? 'Continuous update status' : '持续更新状态' })
  expect(summary).toHaveTextContent(instance.t(enabled ? 'collectorDetail:schedule.autoEnabled' : 'collectorDetail:schedule.manualOnly'))
  expect(within(summary).getByRole('link', { name: language === 'en' ? 'View collection settings' : '查看采集配置' }).getAttribute('href')).toContain('section=config')
  expect(within(summary).queryByRole('button')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: language === 'en' ? 'Rule published; first run pending' : '规则已发布，尚未首次运行' })).toBeInTheDocument()
})

it('distinguishes the rule page limit from the independent collection policy', async () => {
  const collector = { ...seedCollectors[0], status: 'published' as const, latestRunId: null }
  collector.candidate = { ...collector.candidate!, pagination: { type: 'next_link', selector: 'a.next', maxPages: 50, allowCrossHost: false } }
  collector.collectionPolicy = { ...collector.collectionPolicy!, maxPages: 20, maxItems: 300, lookbackDays: 3 }
  vi.spyOn(api, 'collector').mockResolvedValue(collector)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?section=overview']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('连续翻页，最多 50 页')).toBeInTheDocument()
  expect(screen.getByText('策略上限 20 页 · 300 条 · 回看 3 天')).toBeInTheDocument()
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
