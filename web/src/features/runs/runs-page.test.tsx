import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedAiRuns, seedRuns } from '@/api/fixtures'
import type { Run } from '@/api/types'
import { RunsPage } from './runs-page'

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

const runs: Run[] = [
  { ...seedRuns[0], id: 'run_beijing', collectorName: '北京政府采购意向', status: 'succeeded', acceptedCount: 2, rejectedCount: 0 },
  { ...seedRuns[0], id: 'run_shanghai', collectorName: '上海政府采购公告', status: 'partially_succeeded', acceptedCount: 3, rejectedCount: 1 },
]

function renderPage(initialEntry = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <RunsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RunsPage operational list', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ items: runs, page: { nextCursor: null } })))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('uses the toolbar as the first visible surface and renders rows instead of cards', async () => {
    renderPage()

    const toolbar = screen.getByLabelText('运行工具栏')
    const list = await screen.findByLabelText('Run 列表')
    await within(list).findByRole('link', { name: /北京政府采购意向/ })
    expect(screen.getByRole('heading', { name: '运行' })).toHaveClass('sr-only')
    expect(screen.queryByLabelText('运行概览')).not.toBeInTheDocument()
    expect(toolbar.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(list).getAllByRole('link')).toHaveLength(2)
    expect(within(list).getByText('范围与停止')).toBeInTheDocument()
  })

  it('searches rows by collector name and keeps status filtering available', async () => {
    const user = userEvent.setup()
    renderPage()

    const list = await screen.findByLabelText('Run 列表')
    await user.type(screen.getByRole('textbox', { name: '搜索运行' }), '上海')
    expect(within(list).getByText('上海政府采购公告')).toBeInTheDocument()
    expect(within(list).queryByText('北京政府采购意向')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /完整成功/ }))
    expect(within(list).getByText('没有符合当前筛选和搜索的运行。')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '搜索运行' })).toHaveValue('上海')
  })

  it('switches to durable AI task history without adding another sidebar area', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input)
      return url.includes('/ai-runs')
        ? json({ items: seedAiRuns.map(({ attempts: _attempts, ...run }) => run), page: { nextCursor: null } })
        : json({ items: runs, page: { nextCursor: null } })
    }))
    renderPage('/?view=ai')

    const list = await screen.findByLabelText('AI 任务列表')
    expect(screen.getByRole('tab', { name: 'AI 任务' })).toHaveAttribute('aria-selected', 'true')
    expect(await within(list).findByText('候选规则已生成')).toBeInTheDocument()
    expect(within(list).getByText('10.3k')).toBeInTheDocument()
    expect(within(list).queryByText('op_ai_shanghai_0901')).not.toBeInTheDocument()
  })
})
