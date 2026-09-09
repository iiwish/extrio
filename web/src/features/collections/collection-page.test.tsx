import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import i18next, { createInstance, type i18n } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, createRoutesFromElements, Route, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiRequestError } from '@/api/client'
import { seedCollectors } from '@/api/fixtures'
import { AppShell } from '@/app/app-shell'
import { initI18n } from '@/i18n'
import { CollectionPage } from './collection-page'
import { CollectionsPage } from './collections-page'
import { requirement } from './collection-test-data'

function mount(path = '/collections/collection_nationwide_tender', language?: i18n) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(createRoutesFromElements(<Route element={<AppShell />}>
    <Route path="/collections" element={<CollectionsPage />} />
    <Route path="/collections/:collectionId" element={<CollectionPage />} />
  </Route>), { initialEntries: [path] })
  const content = <RouterProvider router={router} />
  return { ...render(<QueryClientProvider client={client}><I18nextProvider i18n={language ?? i18next}>{content}</I18nextProvider></QueryClientProvider>), router, client }
}
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('requirement details', () => {
  it('restores the section from its URL and excludes it from the list return context', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    const mounted = mount('/collections/collection_nationwide_tender?q=全国&status=all&sort=updated_asc&section=sources')
    expect(await screen.findByRole('tab', { name: /关联来源/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('link', { name: '返回采集需求列表' })).toHaveAttribute('href', '/collections?q=%E5%85%A8%E5%9B%BD&status=all&sort=updated_asc')
    await userEvent.setup().click(screen.getByRole('tab', { name: '采集字段' }))
    expect(new URLSearchParams(mounted.router.state.location.search).get('section')).toBeNull()
    await userEvent.setup().click(screen.getByRole('tab', { name: /关联来源/ }))
    const path = mounted.router.state.location.pathname + mounted.router.state.location.search
    mounted.unmount()
    mount(path)
    expect(await screen.findByRole('tab', { name: /关联来源/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('keeps field edits across sections and confirms leaving before discarding them', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    vi.spyOn(api, 'collections').mockResolvedValue([requirement()])
    const update = vi.spyOn(api, 'updateCollection')
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '编辑字段' }))
    await user.click(screen.getByRole('tab', { name: /关联来源/ }))
    expect(screen.getByRole('tab', { name: /采集字段/ })).toHaveTextContent('未保存')
    await user.click(screen.getByRole('link', { name: '返回采集需求列表' }))
    const dialog = await screen.findByRole('dialog', { name: '放弃未保存的字段草稿？' })
    await user.click(within(dialog).getByRole('button', { name: '继续编辑' }))
    await waitFor(() => expect(screen.getByRole('tab', { name: /关联来源/ })).toHaveFocus())
    await user.click(screen.getByRole('tab', { name: /采集字段/ }))
    expect(screen.getByRole('button', { name: '保存字段草稿' })).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: '返回采集需求列表' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '放弃并离开' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: '搜索采集需求' })).toBeInTheDocument())
    expect(update).not.toHaveBeenCalled()
  })

  it('expands a long business goal without altering its original content', async () => {
    const intent = '采集目标与跨地区采购公告。\n'.repeat(30)
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ intent }))
    mount()
    const expand = await screen.findByRole('button', { name: '展开完整目标' })
    expect(expand).toHaveAttribute('aria-expanded', 'false')
    await userEvent.setup().click(expand)
    expect(screen.getByRole('button', { name: '收起目标' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('region', { name: '采集目标' }).querySelector('p')?.textContent).toBe(intent)
  })

  it('does not report zero output fields for an unavailable source contract', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ sources: [seedCollectors[0]], sourceContracts: [{ sourceId: seedCollectors[0].id, sourceName: seedCollectors[0].name, state: 'unavailable', ruleVersion: null, fields: [], schema: {}, quality: {} }] }))
    mount('/collections/collection_nationwide_tender?section=sources')
    expect(await screen.findByRole('cell', { name: '无法确认' })).toBeInTheDocument()
  })

  it('preserves local field edits when a background detail refresh fails', async () => {
    const read = vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    const mounted = mount()
    await userEvent.setup().click(await screen.findByRole('button', { name: '编辑字段' }))
    read.mockRejectedValue(new Error('offline'))
    await act(async () => { await mounted.client.invalidateQueries({ queryKey: ['collection', 'collection_nationwide_tender'] }) })
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.getByRole('button', { name: '保存字段草稿' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /采集字段/ })).toHaveTextContent('未保存')
  })

  it('does not allow a pending field save to be abandoned through the leave dialog', async () => {
    const read = vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    let finish!: (value: ReturnType<typeof requirement>) => void
    vi.spyOn(api, 'updateCollection').mockImplementation(() => new Promise(resolve => { finish = resolve }))
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '编辑字段' }))
    await user.click(screen.getByRole('button', { name: '保存字段草稿' }))
    await user.click(screen.getByRole('link', { name: '返回采集需求列表' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('button', { name: '放弃并离开' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: '继续编辑' })).toBeDisabled()
    const saved = requirement({ revision: 2, fieldDraft: { fields: [] } })
    read.mockResolvedValue(saved)
    await act(async () => finish(saved))
    await waitFor(() => expect(within(dialog).getByRole('button', { name: '继续编辑' })).toBeEnabled())
    await user.click(within(dialog).getByRole('button', { name: '继续编辑' }))
    expect(screen.getByRole('status')).toHaveTextContent('字段草稿已保存')
  })

  it('renders English detail controls and keeps long business content unmodified', async () => {
    const language = initI18n(createInstance())
    await language.changeLanguage('en')
    const name = '全国采购公告 / Cross-regional procurement and public contract requirements'.repeat(2)
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ name, intent: 'Long business intent. '.repeat(30) }))
    mount('/collections/collection_nationwide_tender?section=invalid', language)
    expect(await screen.findByRole('heading', { name })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Collection fields' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: 'Show full intent' })).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Edit fields' }))
    await userEvent.setup().click(screen.getByRole('link', { name: /Back to Requirements/ }))
    expect(await screen.findByRole('dialog', { name: 'Discard unsaved field changes?' })).toBeInTheDocument()
  })

  it('opens requirement details from search, scopes sources by ID and preserves the return filter', async () => {
    const sources = seedCollectors.map((source, index) => index ? { ...source, collectionId: 'another_id' } : source)
    vi.spyOn(api, 'collections').mockResolvedValue([requirement()])
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ sources: [sources[0]], sourceCount: 1 }))
    mount('/collections?q=全国&status=all&sort=updated_asc')
    await userEvent.setup().click((await screen.findAllByRole('link', { name: '全国公共资源交易标讯' }))[0])
    expect(await screen.findByRole('heading', { name: '全国公共资源交易标讯' })).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(2)
    expect(screen.getByRole('tab', { name: '采集字段' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '来源执行字段' })).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('tab', { name: /关联来源/ }))
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    const sourceHref = new URL(within(table).getByRole('link', { name: sources[0].name }).getAttribute('href')!, 'http://localhost')
    expect(sourceHref.pathname).toBe(`/collectors/${sources[0].id}`)
    expect(sourceHref.searchParams.get('returnTo')).toBe('/collections/collection_nationwide_tender?q=%E5%85%A8%E5%9B%BD&status=all&sort=updated_asc&section=sources')
    const createHref = new URL(screen.getByRole('link', { name: '添加来源' }).getAttribute('href')!, 'http://localhost')
    expect(createHref.searchParams.get('collection')).toBe('collection_nationwide_tender')
    expect(createHref.searchParams.get('returnTo')).toBe(sourceHref.searchParams.get('returnTo'))
    await userEvent.setup().click(screen.getByRole('link', { name: '返回采集需求列表' }))
    expect(screen.getByRole('textbox', { name: '搜索采集需求' })).toHaveValue('全国')
    expect(screen.getByRole('button', { name: /全部需求/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('columnheader', { name: '最近更新' })).toHaveAttribute('aria-sort', 'ascending')
  })

  it('does not mistake a request failure for a missing requirement', async () => {
    vi.spyOn(api, 'collection').mockRejectedValueOnce(new Error('offline')).mockRejectedValue(new ApiRequestError({
      code: 'COLLECTION_NOT_FOUND', message: 'missing', requestId: 'test', retryable: false,
    }))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.queryByText('未找到该采集需求')).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('heading', { name: '未找到该采集需求' })).toBeInTheDocument()
  })
})
