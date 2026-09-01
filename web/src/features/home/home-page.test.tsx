import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { HomePage } from './home-page'

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={queryClient}><MemoryRouter><HomePage /></MemoryRouter></QueryClientProvider>)
}

describe('HomePage operational dashboard', () => {
  beforeEach(() => {
    const startedAtIso = new Date(Date.now() - 60 * 60 * 1000).toISOString()
    const dashboardRuns = seedRuns.map((run) => ({ ...run, startedAtIso }))
    const dashboardItems = dashboardRuns.flatMap((run) => run.items.map((item) => ({ ...item, observedAt: startedAtIso })))
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path.endsWith('/collectors')) return json({ items: seedCollectors, page: { nextCursor: null } })
      if (path.endsWith('/runs')) return json({ items: dashboardRuns, page: { nextCursor: null } })
      if (path.endsWith('/items')) return json({ items: dashboardItems, page: { nextCursor: null } })
      return json({ message: 'Not found' })
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('summarizes operational health instead of repeating entity lists', async () => {
    renderPage()

    expect(await screen.findByText('今日采集')).toBeInTheDocument()
    expect(await screen.findByText('1/2')).toBeInTheDocument()
    expect(screen.getByText('采集运营')).toBeInTheDocument()
    const periodControl = screen.getByRole('group', { name: '趋势聚合口径' })
    expect(within(periodControl).getByRole('button', { name: '按日' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('heading', { name: '概览' })).toHaveClass('sr-only')
    expect(screen.queryByText('工作概览')).not.toBeInTheDocument()
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    const metrics = screen.getByRole('region', { name: '核心运营指标' })
    expect(within(metrics).getByText('本周运行成功率')).toBeInTheDocument()
    expect(within(metrics).getByText('本月有效数据')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '采集产出趋势' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '运行质量' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '需要关注' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '系统状态' })).not.toBeInTheDocument()
    expect(screen.queryByText('当前最优先')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '最近数据' })).not.toBeInTheDocument()
  })

  it('uses an aggregated trend and a short exception list without exposing technical IDs', async () => {
    renderPage()

    const trend = await screen.findByRole('group', { name: /最近 14 天 1 次运行/ })
    expect(trend.querySelectorAll('.overview-chart-point')).toHaveLength(14)
    const attention = screen.getByRole('region', { name: '需要关注' })
    expect(within(attention).getByRole('link', { name: /处理部分成功运行.*上海政府采购公告/ })).toHaveAttribute('href', '/runs/run_0842')
    expect(screen.queryByText('run_0842')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '最近运行' })).not.toBeInTheDocument()
    expect(screen.queryByText('继续上次工作')).not.toBeInTheDocument()
    expect(screen.queryByText('数据质量分')).not.toBeInTheDocument()
  })

  it('changes trend aggregation without turning the entire dashboard into a period switcher', async () => {
    renderPage()

    await screen.findByRole('group', { name: /最近 14 天 1 次运行/ })
    const periodControl = screen.getByRole('group', { name: '趋势聚合口径' })

    fireEvent.click(within(periodControl).getByRole('button', { name: '按周' }))
    expect(screen.getByRole('group', { name: /最近 12 周 1 次运行/ }).querySelectorAll('.overview-chart-point')).toHaveLength(12)

    fireEvent.click(within(periodControl).getByRole('button', { name: '按月' }))
    expect(within(periodControl).getByRole('button', { name: '按月' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('group', { name: /最近 12 个月 1 次运行/ }).querySelectorAll('.overview-chart-point')).toHaveLength(12)
    expect(screen.getByText('今日采集')).toBeInTheDocument()
    expect(screen.getByText('本周运行成功率')).toBeInTheDocument()
  })
})
