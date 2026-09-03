import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedRuns } from '@/api/fixtures'
import { ItemsPage } from './items-page'

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

function renderPage(initialUrl = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <ItemsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ItemsPage operational list', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ items: seedRuns[0].items, page: { nextCursor: null } })))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    delete (URL as unknown as { createObjectURL?: unknown }).createObjectURL
    delete (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL
  })

  it('uses a filter-first toolbar and renders fixed-column rows instead of cards', async () => {
    renderPage()

    const toolbar = screen.getByLabelText('数据工具栏')
    const list = await screen.findByLabelText('Item 列表')
    const rows = await within(list).findAllByRole('link')
    expect(screen.getByRole('heading', { name: '数据' })).toHaveClass('sr-only')
    expect(screen.queryByLabelText('数据概览')).not.toBeInTheDocument()
    expect(toolbar.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(toolbar).getByRole('combobox', { name: '按 Source 筛选' }).compareDocumentPosition(within(toolbar).getByRole('textbox', { name: '搜索 Item' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(list).getByText('变化 / Revision')).toBeInTheDocument()
    expect(rows[0]).toHaveClass('object-row')
    expect(rows[0]).not.toHaveClass('entity-card')
    const sourceContext = rows[0].querySelector('.object-primary small')?.textContent ?? ''
    expect(sourceContext.split(seedRuns[0].items[0].sourceHost)).toHaveLength(2)
  })

  it('searches the list while leaving source, collector, and decision filters available', async () => {
    const user = userEvent.setup()
    renderPage()

    const list = await screen.findByLabelText('Item 列表')
    const rows = await within(list).findAllByRole('link')
    const targetTitle = rows[0].querySelector('strong')?.textContent ?? ''
    await user.type(screen.getByRole('textbox', { name: '搜索 Item' }), targetTitle.slice(0, 5))

    expect(within(list).getAllByRole('link').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByRole('combobox', { name: '按 Source 筛选' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '按 Collector 筛选' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '质量决定筛选' })).toBeInTheDocument()
  })

  it('exports CSV carrying the URL filter state as query params and downloads the blob', async () => {
    const user = userEvent.setup()
    URL.createObjectURL = vi.fn(() => 'blob:export-mock')
    URL.revokeObjectURL = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/v1/items/export') {
        return new Response('entityKey,decision\n', { status: 200, headers: { 'Content-Type': 'text/csv' } })
      }
      return json({ items: seedRuns[0].items, page: { nextCursor: null } })
    }))
    renderPage('/items?collector=collector_shanghai_procurement&decision=accepted&q=KEY-2026')

    await user.click(screen.getByRole('button', { name: '导出当前筛选的数据' }))
    await user.click(await screen.findByText('导出 CSV'))

    await waitFor(() => {
      const exportCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes('/items/export'))
      expect(exportCall).toBeTruthy()
    })
    const exportUrl = new URL(String(vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes('/items/export'))?.[0]), 'http://localhost')
    expect(exportUrl.searchParams.get('format')).toBe('csv')
    expect(exportUrl.searchParams.get('collectorId')).toBe('collector_shanghai_procurement')
    expect(exportUrl.searchParams.get('decision')).toBe('accepted')
    expect(exportUrl.searchParams.get('entityKey')).toBe('KEY-2026')
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:export-mock')
  })

  it('maps EXPORT_TOO_LARGE failures to a scoped filter hint', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/v1/items/export') {
        return new Response(JSON.stringify({ code: 'EXPORT_TOO_LARGE', message: 'export cap exceeded', requestId: 'req_export_cap', retryable: false }), { status: 400, headers: { 'Content-Type': 'application/json' } })
      }
      return json({ items: seedRuns[0].items, page: { nextCursor: null } })
    }))
    renderPage()

    await screen.findByLabelText('Item 列表')
    await user.click(screen.getByRole('button', { name: '导出当前筛选的数据' }))
    await user.click(await screen.findByText('导出 JSONL'))

    expect(await screen.findByText('导出数据量超过上限，请缩小筛选范围')).toBeInTheDocument()
  })
})
