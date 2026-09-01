import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { CollectorsPage } from './collectors-page'

function json(data: unknown) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CollectorsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CollectorsPage operational list', () => {
  beforeEach(() => {
    const collectors = seedCollectors.map((collector, index) => ({
      ...collector,
      collectionId: index === 0 ? 'collection_tender' : 'collection_procurement',
      collectionName: index === 0 ? '全国公共资源交易标讯' : '政府采购公告',
    }))
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path.endsWith('/collectors')) return json({ items: collectors, page: { nextCursor: null } })
      if (path.endsWith('/runs')) return json({ items: seedRuns, page: { nextCursor: null } })
      return json({ message: 'Not found' })
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders a fixed-column list without layout switching or redundant labels', async () => {
    renderPage()

    const list = await screen.findByLabelText('Collector 列表')
    await within(list).findByRole('link', { name: /北京市公共资源交易标讯/ })
    const toolbar = screen.getByLabelText('采集器工具栏')
    expect(within(toolbar).getByRole('link', { name: '新建采集器' })).toHaveAttribute('href', '/collectors/new')
    expect(screen.queryByLabelText('采集器概览')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '采集器' })).toHaveClass('sr-only')
    expect(within(toolbar).queryByRole('group', { name: 'Collector 列表布局' })).not.toBeInTheDocument()
    expect(within(toolbar).queryByText('采集需求')).not.toBeInTheDocument()
    expect(within(list).getByText('所属需求')).toBeInTheDocument()
    expect(within(list).getAllByRole('link')).toHaveLength(2)
    expect(within(list).getAllByRole('link')[0]).toHaveClass('object-row')
    expect(within(list).getAllByRole('link')[0]).not.toHaveClass('entity-card')
  })

  it('searches Collection options before filtering the list', async () => {
    const user = userEvent.setup()
    renderPage()

    const combobox = await screen.findByRole('combobox', { name: '按采集需求筛选' })
    await user.click(combobox)
    await user.type(screen.getByRole('textbox', { name: '搜索采集需求' }), '政府采购')

    const listbox = screen.getByRole('listbox', { name: '采集需求' })
    expect(within(listbox).getByRole('option', { name: /政府采购公告/ })).toBeInTheDocument()
    expect(within(listbox).queryByRole('option', { name: /全国公共资源交易标讯/ })).not.toBeInTheDocument()

    await user.click(within(listbox).getByRole('option', { name: /政府采购公告/ }))
    expect(combobox).toHaveTextContent('政府采购公告')
    expect(screen.getByRole('link', { name: '新建采集器' })).toHaveAttribute('href', '/collectors/new?collection=collection_procurement')
  })
})
