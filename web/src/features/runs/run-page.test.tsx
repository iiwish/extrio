import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { RunPage } from './run-page'
import i18next, { createInstance, type i18n } from 'i18next'
import { I18nextProvider, setI18n } from 'react-i18next'
import { initI18n } from '@/i18n'

const runCollector = seedCollectors.find((item) => item.id === seedRuns[0].collectorId)!
const collectorWithPath = { ...runCollector, sourceUrl: new URL('/notices/list?region=sh', runCollector.sourceUrl).toString() }

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

function renderPage(search = '', language: i18n = i18next) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <I18nextProvider i18n={language}><QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/runs/${seedRuns[0].id}${search}`]}>
        <Routes><Route path="/runs/:runId" element={<RunPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider></I18nextProvider>,
  )
}

describe('RunPage information architecture', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/evidence')) return json({ mode: 'sampled', state: 'expired', fileCount: 1, totalBytes: 0, expiresAt: '2026-01-01T00:00:00Z', canReplay: false, replayReason: 'complete_replayable_evidence_unavailable' })
      return json(url.includes('/collectors/') ? collectorWithPath : seedRuns[0])
    }))
  })

  afterEach(() => {
    cleanup()
    setI18n(i18next)
    vi.unstubAllGlobals()
  })

  it('leads with the collector and keeps the main views at the top', async () => {
    renderPage()

    const heading = await screen.findByRole('heading', { level: 1 })
    const source = new URL(collectorWithPath.sourceUrl)
    await waitFor(() => expect(heading).toHaveTextContent(source.origin))
    expect(heading).not.toHaveTextContent(`${source.pathname}${source.search}`)
    expect(screen.getByText(`${source.pathname}${source.search}${source.hash}`)).toBeInTheDocument()
    expect(heading).not.toHaveTextContent(seedRuns[0].id)
    expect(screen.queryByText('运行记录')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '运行' })).not.toBeInTheDocument()

    const tablist = screen.getByRole('tablist', { name: '运行详情视图' })
    expect(tablist).toHaveAttribute('data-variant', 'line')
    expect(within(tablist).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      `结果${seedRuns[0].acceptedCount + seedRuns[0].rejectedCount}`,
      '执行过程',
      '范围与增量',
      '质量与证据',
    ])
    const summary = screen.getByLabelText('运行结果摘要')
    expect(summary).toHaveClass('detail-panel')
    expect(summary).toHaveTextContent(`接收${seedRuns[0].acceptedCount}`)
    expect(summary).toHaveTextContent(`拒绝${seedRuns[0].rejectedCount}`)
    expect(screen.getByRole('heading', { name: '数据结果' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Run 执行证据')).not.toBeInTheDocument()
  })

  it('summarizes trust before exposing technical identifiers', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('heading', { level: 1 })

    await user.click(screen.getByRole('tab', { name: '质量与证据' }))

    expect(screen.getByRole('heading', { name: '质量结果' })).toBeInTheDocument()
    expect(screen.getByLabelText('运行可信证据')).toHaveTextContent('规则证明已验证')
    expect(screen.getByText('技术信息')).toBeInTheDocument()
    expect(await screen.findByText('原始证据已到期')).toBeInTheDocument()
    expect(screen.getByText('无完整可回放证据')).toBeInTheDocument()
    expect(screen.queryByText('网络边界通过')).not.toBeInTheDocument()
  })

  it.each([['succeeded', 0], ['partially_succeeded', 0], ['partially_succeeded', 1]] as const)('distinguishes page limits from rejected records (%s, %i rejected)', async (status, rejectedCount) => {
    const run = { ...seedRuns[0], status, paginationStopReason: 'max_pages', acceptedCount: 200, rejectedCount, listPagesFetched: 20 }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => json(String(input).includes('/collectors/') ? collectorWithPath : run)))
    renderPage()
    if (rejectedCount === 0) {
      expect(await screen.findByText('已达到页数上限，数据已保存')).toBeInTheDocument()
      expect(screen.getByText(/已采集 20 个列表页，保存 200 条数据/)).toBeInTheDocument()
      expect(screen.queryByText('部分结果需要处理')).not.toBeInTheDocument()
      expect(screen.queryByRole('link', { name: '修订采集规则' })).not.toBeInTheDocument()
    } else {
      expect(await screen.findByText('部分结果需要处理')).toBeInTheDocument()
      expect(screen.queryByText('已达到页数上限，数据已保存')).not.toBeInTheDocument()
    }
  })

  it('persists cancellation without pretending the worker has stopped', async () => {
    let cancelled = false
    const active = { ...seedRuns[0], status: 'running', operationId: 'op_cancel', items: [] }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/cancel') && init?.method === 'POST') cancelled = true
      if (url.includes('/operations/')) return json({ id: 'op_cancel', status: 'running', phase: 'fetching_details', pollAfterMs: 10000, cancelRequested: cancelled })
      return json(url.includes('/collectors/') ? collectorWithPath : active)
    }))
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: '取消运行' }))
    expect(screen.queryByRole('heading', { name: /条数据已完成质量终结/ })).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '等待停止' })).toBeDisabled()
    expect(screen.queryByText('运行已取消，结果未进入交付集')).not.toBeInTheDocument()
  })

  it('separates unfetched pages from quality rejections and opens this run\'s rejected set', async () => {
    const accepted = { ...seedRuns[0].items[0], id: 'accepted-test', title: 'Accepted test', decision: 'accepted' }
    const items = [accepted, ...['one', 'two'].map(id => ({ ...accepted, id, title: `Rejected ${id}`, decision: 'rejected' }))]
    const run = { ...seedRuns[0], status: 'partially_succeeded', items, acceptedCount: 1, rejectedCount: 2, detailUrlsDiscovered: 11, detailPagesFetched: 3, paginationStopReason: 'detail_fetch_incomplete' }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => json(String(input).includes('/collectors/') ? collectorWithPath : run)))
    renderPage()
    expect(await screen.findByText('8 个详情页面未获取')).toBeInTheDocument()
    expect(screen.getByText('2 条数据未通过质量检查')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '查看本次拒绝项' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: '数据结果' })).toHaveFocus())
    expect(screen.getByRole('button', { name: '仅拒绝' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('link', { name: /Accepted test/ })).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Rejected/ })).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: '查看执行诊断' }))
    await waitFor(() => expect(screen.getByRole('tab', { name: '执行过程' })).toHaveFocus())
    expect(screen.getByRole('tab', { name: '执行过程' })).toHaveAttribute('aria-selected', 'true')
  })

  it('does not send a network failure to rule editing', async () => {
    const run = { ...seedRuns[0], status: 'failed', operationId: 'failed-op', items: [] }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => json(String(input).includes('/operations/') ? { id: 'failed-op', status: 'failed', error: { code: 'SOURCE_NETWORK_REJECTED', details: { reason: 'dns_resolution_failed' } } } : String(input).includes('/collectors/') ? collectorWithPath : run)))
    renderPage()
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByRole('link', { name: '修订采集规则' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '查看执行诊断' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '查看执行诊断' }))
    expect(await screen.findByText(/SOURCE_NETWORK_REJECTED/)).toHaveTextContent('dns_resolution_failed')
  })

  it('renders English recovery groups without translating source content', async () => {
    const language = initI18n(createInstance())
    await language.changeLanguage('en')
    const run = { ...seedRuns[0], status: 'partially_succeeded', rejectedCount: 2, detailUrlsDiscovered: 5, detailPagesFetched: 3, summary: '原始来源诊断' }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => json(String(input).includes('/collectors/') ? collectorWithPath : run)))
    renderPage('', language)
    expect(await screen.findByText('2 detail pages not fetched')).toBeInTheDocument()
    expect(screen.getByText('2 records failed quality checks')).toBeInTheDocument()
    expect(screen.getByText('原始来源诊断')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: "View this run's rejections" }))
    expect(screen.getByRole('button', { name: 'Rejected only' })).toHaveAttribute('aria-pressed', 'true')
  })

  it.each([0, 2])('restores the rejected filter and distinguishes empty from unavailable (%i rejected)', async rejectedCount => {
    const run = { ...seedRuns[0], status: 'succeeded', rejectedCount, items: [] }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => json(String(input).includes('/collectors/') ? collectorWithPath : run)))
    renderPage('?section=results&decision=rejected&returnTo=%2Fruns')
    expect(await screen.findByRole('button', { name: '仅拒绝' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(rejectedCount ? '本次有拒绝记录，但详情当前不可用。' : '本次运行没有拒绝项。')).toBeInTheDocument()
    if (rejectedCount) expect(screen.getByRole('status')).toHaveTextContent('已加载 0/2 条拒绝项')
  })

  it('does not suppress incomplete fetching when a partial run also reached its page limit', async () => {
    const run = { ...seedRuns[0], status: 'partially_succeeded', paginationStopReason: 'max_pages', rejectedCount: 0, detailUrlsDiscovered: 5, detailPagesFetched: 3 }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => json(String(input).includes('/collectors/') ? collectorWithPath : run)))
    renderPage()
    expect(await screen.findByText('2 个详情页面未获取')).toBeInTheDocument()
    expect(screen.queryByText('已达到页数上限，数据已保存')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看规则与证据' })).not.toBeInTheDocument()
  })

  it('keeps deleted-source history readable without requesting or linking the source', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).not.toContain('/collectors/')
      return json({ ...seedRuns[0], collectorDeleted: true })
    })
    vi.stubGlobal('fetch', fetcher)
    renderPage()
    expect(await screen.findByText('来源已删除')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '数据结果' })).toBeInTheDocument()
    expect(screen.queryAllByRole('link').some(link => link.getAttribute('href')?.startsWith('/collectors/'))).toBe(false)
    expect(fetcher.mock.calls.some(call => String(call[0]).includes('/collectors/'))).toBe(false)
  })
})
