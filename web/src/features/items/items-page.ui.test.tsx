import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedRuns } from '@/api/fixtures'
import { ItemsPage } from './items-page'

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
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
})
