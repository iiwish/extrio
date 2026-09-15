import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import i18next, { createInstance, type i18n } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, createRoutesFromElements, Route, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiRequestError } from '@/api/client'
import { mockCollectionPage } from '@/api/workspace-mock'
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
  it('prioritizes the requirement name and gives all five source columns explicit tracks', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    const { container } = mount('/collections/collection_nationwide_tender?section=sources')
    expect(await screen.findByRole('heading', { level: 1, name: requirement().name })).toBeInTheDocument()
    expect(container.querySelector('.requirement-title-row')?.firstElementChild?.tagName).toBe('H1')
    expect(container.querySelectorAll('.collection-sources-table col')).toHaveLength(5)
    expect(screen.getByRole('columnheader', { name: '输出字段数' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '编辑来源' })).toBeInTheDocument()
  })

  it('shows unresolved target alignment before opening sources and excludes archived sources', async () => {
    const sources = [{ ...seedCollectors[0], lifecycle: 'active' as const }, { ...seedCollectors[1], lifecycle: 'archived' as const }]
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ sources, activeVersionId: 'target', activeVersion: { id: 'target', versionNumber: 2, fieldCount: 1, outputContractDigest: 'digest', publishedAt: '2026-09-14T00:00:00Z' }, sourceContracts: sources.map(source => ({ sourceId: source.id, sourceName: source.name, state: 'published', ruleVersion: 'rule', fields: [], schema: {}, quality: {}, targetVersionNumber: 2, sourceVersionNumber: 1, isAligned: false })) }))
    const { router } = mount('/collections/collection_nationwide_tender?q=全国')
    expect(await screen.findByText('1 个采集来源尚未应用最新字段要求')).toBeInTheDocument()
    expect(screen.getByText('需求字段已发布为 v2，这些来源仍按原规则采集，不会自动更新。')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '查看来源字段版本' }))
    await waitFor(() => expect(screen.getByRole('tab', { name: /关联来源/ })).toHaveFocus())
    expect(screen.getByRole('tab', { name: /关联来源/ })).toHaveAttribute('aria-selected', 'true')
    expect(new URLSearchParams(router.state.location.search).get('q')).toBe('全国')
  })

  it('does not treat missing alignment metadata as aligned', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ sources: [seedCollectors[0]], activeVersionId: 'target', activeVersion: { id: 'target', versionNumber: 2, fieldCount: 1, outputContractDigest: 'digest', publishedAt: '2026-09-14T00:00:00Z' } }))
    mount()
    expect(await screen.findByText('1 个活动来源的版本无法确认')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '查看来源字段版本' }))
    expect(screen.queryByText(/\(已对齐\)/)).not.toBeInTheDocument()
  })

  it('creates in place with a fixed requirement ID and refreshes linked sources', async () => {
    const empty = requirement({ sources: [], sourceCount: 0 })
    const source = { ...seedCollectors[0], id: 'added-source', collectionId: empty.id, name: '新增来源' }
    const read = vi.spyOn(api, 'collection').mockResolvedValue(empty)
    const create = vi.spyOn(api, 'createCollectors').mockImplementation(async () => {
      read.mockResolvedValue(requirement({ sources: [source], sourceCount: 1 }))
      return { collectionId: empty.id, collectionName: empty.name, collectionVersion: 'v1', total: 1, createdCount: 1, rejectedCount: 0, results: [{ status: 'created', collector: source, error: null, sourceUrl: 'https://example.com/list' }] }
    })
    const { router } = mount('/collections/collection_nationwide_tender?q=全国')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '添加来源' }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'https://example.com/list')
    await user.click(within(dialog).getByRole('button', { name: '添加来源' }))
    expect(await screen.findByRole('link', { name: '新增来源' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '添加来源' })).toHaveFocus())
    expect(screen.getByRole('tab', { name: '关联来源 · 1' })).toHaveAttribute('aria-selected', 'true')
    expect(router.state.location.pathname).toBe(`/collections/${empty.id}`)
    expect(new URLSearchParams(router.state.location.search).get('q')).toBe('全国')
    expect(create).toHaveBeenCalledWith({ collectionId: empty.id, collectionName: empty.name, intent: empty.intent, sources: [{ entryUrl: 'https://example.com/list', mode: 'exact' }] }, expect.any(String))
  })

  it('retains failed input and requires confirmation to discard it', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    const create = vi.spyOn(api, 'createCollectors').mockRejectedValue(new Error('offline'))
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '添加来源' }))
    const dialog = screen.getByRole('dialog')
    const input = within(dialog).getByRole('textbox')
    await user.type(input, 'https://example.com/')
    expect(within(dialog).getByRole('button', { name: '添加来源' })).toBeDisabled()
    await user.clear(input)
    await user.type(input, 'https://example.com/list')
    await user.click(within(dialog).getByRole('button', { name: '添加来源' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('offline')
    expect(input).toHaveValue('https://example.com/list')
    await user.click(within(dialog).getByRole('button', { name: '取消' }))
    await user.click(within(dialog).getByRole('button', { name: '继续编辑' }))
    expect(input).toHaveValue('https://example.com/list')
    await user.click(within(dialog).getByRole('button', { name: '添加来源' }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2))
    expect(create.mock.calls[0][1]).toBe(create.mock.calls[1][1])
  })

  it('keeps rejected rows visible and does not retry successfully created rows', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    const create = vi.spyOn(api, 'createCollectors').mockResolvedValue({ collectionId: requirement().id, collectionName: 'Need', collectionVersion: 'v1', total: 2, createdCount: 1, rejectedCount: 1, results: [
      { status: 'created', collector: seedCollectors[0], error: null, sourceUrl: 'https://example.com/list' },
      { status: 'rejected', collector: null, sourceUrl: 'https://example.com/other', error: { code: 'SOURCE_ALREADY_EXISTS', message: '该 Source URL 已存在', requestId: 'test', retryable: false } },
    ] })
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '添加来源' }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'https://example.com/list\nhttps://example.com/other')
    await user.click(within(dialog).getByRole('button', { name: '添加来源' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('已添加 1 个来源，1 个未添加')
    await waitFor(() => expect(within(dialog).getByRole('button', { name: '添加来源' })).toBeEnabled())
    expect(within(dialog).getByRole('textbox')).toHaveValue('https://example.com/other')
    expect(within(dialog).getByRole('alert')).toHaveTextContent('该 Source URL 已存在')
    await user.click(within(dialog).getByRole('button', { name: '添加来源' }))
    expect(create.mock.calls[1][0].sources).toEqual([{ entryUrl: 'https://example.com/other', mode: 'exact' }])
  })

  it('cannot close or edit the source dialog during submission', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    let reject!: (error: Error) => void
    vi.spyOn(api, 'createCollectors').mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '添加来源' }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'https://example.com/list')
    await user.click(within(dialog).getByRole('button', { name: '添加来源' }))
    expect(within(dialog).getByRole('textbox')).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: '取消' })).toBeDisabled()
    expect(within(dialog).queryByRole('button', { name: '关闭' })).not.toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(dialog).toBeInTheDocument()
    await act(async () => reject(new Error('offline')))
    await waitFor(() => expect(within(dialog).getByRole('button', { name: '取消' })).toBeEnabled())
  })

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
    vi.spyOn(api, 'collectionsPage').mockResolvedValue(mockCollectionPage(new URLSearchParams(), [requirement()]))
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
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ name, intent: 'Long business intent. '.repeat(30), activeVersionId: 'target', activeVersion: { id: 'target', versionNumber: 2, fieldCount: 1, outputContractDigest: 'digest', publishedAt: '2026-09-14T00:00:00Z' } }))
    mount('/collections/collection_nationwide_tender?section=invalid', language)
    expect(await screen.findByRole('heading', { name })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Collection fields' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: 'Show full intent' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View source field versions' })).toBeInTheDocument()
    expect(screen.getByText('Version unknown for 2 active sources')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Edit fields' }))
    await userEvent.setup().click(screen.getByRole('link', { name: /Back to Requirements/ }))
    expect(await screen.findByRole('dialog', { name: 'Discard unsaved field changes?' })).toBeInTheDocument()
  })

  it('opens requirement details from search, scopes sources by ID and preserves the return filter', async () => {
    const sources = seedCollectors.map((source, index) => index ? { ...source, collectionId: 'another_id' } : source)
    vi.spyOn(api, 'collectionsPage').mockResolvedValue(mockCollectionPage(new URLSearchParams(), [requirement()]))
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
    await userEvent.setup().click(screen.getByRole('button', { name: '添加来源' }))
    expect(await screen.findByRole('dialog', { name: '添加来源' })).toHaveTextContent('全国公共资源交易标讯')
    expect(screen.queryByRole('combobox', { name: '选择已有需求' })).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '取消' }))
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
