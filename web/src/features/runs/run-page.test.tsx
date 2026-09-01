import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { RunPage } from './run-page'

const runCollector = seedCollectors.find((item) => item.id === seedRuns[0].collectorId)!
const collectorWithPath = { ...runCollector, sourceUrl: new URL('/notices/list?region=sh', runCollector.sourceUrl).toString() }

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/runs/${seedRuns[0].id}`]}>
        <Routes><Route path="/runs/:runId" element={<RunPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RunPage information architecture', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      return json(url.includes('/collectors/') ? collectorWithPath : seedRuns[0])
    }))
  })

  afterEach(() => {
    cleanup()
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
  })
})
