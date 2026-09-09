import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createInstance, type i18n } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { AuthGate } from '@/features/auth/auth-gate'
import { initI18n } from '@/i18n'
import { requirement } from './collection-test-data'
import { CollectionsPage } from './collections-page'

function LocationProbe() {
  return <span data-testid="location">{useLocation().search}</span>
}
function mount(path = '/collections', auth = false, language?: i18n) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const content = <><CollectionsPage /><LocationProbe /></>
  const page = language ? <I18nextProvider i18n={language}>{content}</I18nextProvider> : content
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{auth ? <AuthGate>{page}</AuthGate> : page}</MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.restoreAllMocks() })
describe('live requirement navigation', () => {
  it('lists independent backend requirements and links to their detail', async () => {
    vi.spyOn(api, 'collections').mockResolvedValue([requirement()])
    mount()
    const table = await screen.findByRole('table')
    const row = await within(table).findByRole('link', { name: '全国公共资源交易标讯' })
    expect(row).toHaveAttribute('href', '/collections/collection_nationwide_tender')
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(screen.getByRole('link', { name: '新建需求' })).toHaveAttribute('href', '/collections/new')
  })
  it('distinguishes failed loading from an empty requirement list and retries', async () => {
    const query = vi.spyOn(api, 'collections').mockRejectedValueOnce(new Error('offline')).mockResolvedValue([])
    mount()
    const retry = await screen.findByRole('button', { name: '重试' })
    expect(screen.queryByText('尚无采集需求')).not.toBeInTheDocument()
    await userEvent.setup().click(retry)
    expect(await screen.findByText('尚无采集需求')).toBeInTheDocument()
    expect(query).toHaveBeenCalledTimes(2)
  })
  it('keeps identically named requirements separate and supports search', async () => {
    vi.spyOn(api, 'collections').mockResolvedValue([requirement({ id: 'one' }), requirement({ id: 'two', sources: [], sourceCount: 0 })])
    mount()
    await screen.findAllByRole('link', { name: '全国公共资源交易标讯' })
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3)
    await userEvent.setup().type(screen.getByRole('textbox', { name: '搜索采集需求' }), '不存在')
    expect(screen.getByText('没有匹配的采集需求')).toBeInTheDocument()
  })

  it('does not report zero requirements while loading or after a failed read', async () => {
    let reject!: (reason: Error) => void
    vi.spyOn(api, 'collections').mockReturnValue(new Promise((_resolve, fail) => { reject = fail }))
    mount()
    expect(screen.queryByText('0 个需求')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('加载中')
    reject(new Error('offline'))
    await screen.findByRole('alert')
    expect(screen.queryByText('0 个需求')).not.toBeInTheDocument()
    expect(screen.queryByText('尚无采集需求')).not.toBeInTheDocument()
  })

  it('keeps the status filter when clearing search and restores focus to search', async () => {
    vi.spyOn(api, 'collections').mockResolvedValue([
      requirement({ id: 'archived', name: '归档标讯', status: 'archived' }),
      requirement({ id: 'active', name: '使用中标讯' }),
    ])
    mount('/collections?status=archived&q=不存在&sort=updated_asc')
    await screen.findByText('没有匹配的采集需求')
    const input = screen.getByRole('textbox', { name: '搜索采集需求' })
    await userEvent.setup().click(screen.getByRole('button', { name: '清除搜索' }))
    expect(await screen.findByRole('link', { name: '归档标讯' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '使用中标讯' })).not.toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('status=archived&sort=updated_asc')
    expect(input).toHaveFocus()
  })

  it('exposes status counts and distinguishes an empty archived view from search misses', async () => {
    vi.spyOn(api, 'collections').mockResolvedValue([requirement()])
    mount()
    const group = screen.getByRole('group', { name: '需求状态' })
    await screen.findByRole('table')
    expect(within(group).getByRole('button', { name: /使用中/ })).toHaveTextContent('1')
    await userEvent.setup().click(within(group).getByRole('button', { name: /已归档/ }))
    expect(await screen.findByRole('heading', { name: '暂无已归档需求' })).toBeInTheDocument()
    expect(screen.queryByText('没有匹配的采集需求')).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '查看使用中的需求' }))
    expect(await screen.findByRole('link', { name: '全国公共资源交易标讯' })).toBeInTheDocument()
  })

  it('sorts by last update with a deterministic tie break and preserves the detail query', async () => {
    vi.spyOn(api, 'collections').mockResolvedValue([
      requirement({ id: 'older', name: 'Older', updatedAt: '2026-09-01T00:00:00Z' }),
      requirement({ id: 'z', name: 'Latest Z', updatedAt: '2026-09-06T00:00:00Z' }),
      requirement({ id: 'a', name: 'Latest A', updatedAt: '2026-09-06T00:00:00Z' }),
    ])
    mount('/collections?status=all')
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('link').map(link => link.textContent)).toEqual(['Latest A', 'Latest Z', 'Older'])
    const heading = screen.getByRole('columnheader', { name: /最近更新/ })
    expect(heading).toHaveAttribute('aria-sort', 'descending')
    await userEvent.setup().click(within(heading).getByRole('button'))
    expect(within(table).getAllByRole('link').map(link => link.textContent)).toEqual(['Older', 'Latest A', 'Latest Z'])
    expect(heading).toHaveAttribute('aria-sort', 'ascending')
    expect(within(table).getByRole('link', { name: 'Older' })).toHaveAttribute('href', '/collections/older?status=all&sort=updated_asc')
  })

  it('shows source publication without equating it to running health or a frozen field version', async () => {
    vi.spyOn(api, 'collections').mockResolvedValue([
      requirement({ id: 'empty', name: 'Empty', sourceCount: 0, publishedSourceCount: 0 }),
      requirement({ id: 'partial', name: 'Partial', sourceCount: 3, publishedSourceCount: 1 }),
    ])
    mount()
    const table = await screen.findByRole('table')
    expect(within(table).getByText('尚无来源')).toBeInTheDocument()
    expect(within(table).getByText('2 个来源待发布')).toBeInTheDocument()
    expect(within(table).getByRole('columnheader', { name: '合同引用' })).toBeInTheDocument()
    expect(within(table).queryByRole('columnheader', { name: '字段版本' })).not.toBeInTheDocument()
    expect(within(table).queryByText('运行正常')).not.toBeInTheDocument()
  })

  it('refreshes without clearing filters or hiding existing results', async () => {
    let finish!: (value: ReturnType<typeof requirement>[]) => void
    const read = vi.spyOn(api, 'collections').mockResolvedValueOnce([requirement()])
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    mount('/collections?q=全国&status=active')
    await screen.findByRole('table')
    const refresh = screen.getByRole('button', { name: '刷新需求列表' })
    await userEvent.setup().click(refresh)
    expect(refresh).toBeDisabled()
    expect(screen.getByRole('link', { name: '全国公共资源交易标讯' })).toBeInTheDocument()
    finish([requirement()])
    await waitFor(() => expect(refresh).not.toBeDisabled())
    expect(read).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('textbox', { name: '搜索采集需求' })).toHaveValue('全国')
  })

  it('keeps viewer access read-only while retaining filtering and refresh', async () => {
    vi.spyOn(api, 'collections').mockResolvedValue([requirement()])
    vi.spyOn(api, 'authState').mockResolvedValue({ authEnabled: true, authenticated: true, setupRequired: false,
      user: { id: 'viewer', username: 'viewer', displayName: 'Viewer', role: 'viewer' } })
    mount('/collections', true)
    await screen.findByRole('table')
    expect(screen.queryByRole('link', { name: '新建需求' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新需求列表' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '需求状态' })).toBeInTheDocument()
  })

  it('renders English controls and preserves long source content and technical identifiers', async () => {
    const language = initI18n(createInstance())
    await language.changeLanguage('en')
    const name = '跨地区公共采购 / Cross-regional procurement requirements and contract notices'
    const intent = '保留原始内容与链接。 Collect contract notices, award decisions and procurement plans.\n'.repeat(8)
    const contract = 'procurement_contract_reference_with_an_unusually_long_identifier_v12'
    vi.spyOn(api, 'collections').mockResolvedValue([requirement({ name, intent, collectionVersion: contract, sourceCount: 3, publishedSourceCount: 1 })])
    mount('/collections', false, language)
    const table = await screen.findByRole('table', { name: 'Requirements' })
    expect(within(table).getByRole('link', { name })).toBeInTheDocument()
    expect(within(table).getByTitle(intent, { normalizer: value => value }).textContent).toBe(intent)
    expect(within(table).getByText(contract)).toBeInTheDocument()
    expect(within(table).getByText('2 sources awaiting publication')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh requirements' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Last updated' })).toHaveAttribute('aria-sort', 'descending')
    await userEvent.setup().click(screen.getByRole('button', { name: /Archived/ }))
    expect(screen.getByRole('heading', { name: 'No archived requirements' })).toBeInTheDocument()
  })
})
