import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, createRoutesFromElements, Route, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiRequestError } from '@/api/client'
import { AuthGate } from '@/features/auth/auth-gate'
import { CollectionPage } from './collection-page'
import { CollectionsPage } from './collections-page'
import { NewCollectionPage } from './new-collection-page'
import { requirement } from './collection-test-data'

function mount(path = '/collections/collection_nationwide_tender', auth = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(createRoutesFromElements(<><Route path="/collections" element={<CollectionsPage />} /><Route path="/collections/new" element={<NewCollectionPage />} /><Route path="/collections/:collectionId" element={<CollectionPage />} /></>), { initialEntries: [path] })
  const routes = <RouterProvider router={router} />
  return render(<QueryClientProvider client={client}>{auth ? <AuthGate>{routes}</AuthGate> : routes}</QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('requirement CRUD', () => {
  it('reuses the command key when retrying an uncertain create response', async () => {
    const value = requirement({ sources: [], sourceCount: 0 })
    const create = vi.spyOn(api, 'createCollection').mockRejectedValueOnce(new Error('offline')).mockResolvedValue(value)
    vi.spyOn(api, 'collection').mockResolvedValue(value)
    mount('/collections/new')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('需求名称'), 'Need')
    await user.type(screen.getByLabelText('采集目标'), 'Goal')
    await user.click(screen.getByRole('button', { name: '创建需求' }))
    expect(await within(screen.getByRole('dialog', { name: '新建需求' })).findByRole('alert')).toHaveTextContent('offline')
    await user.click(screen.getByRole('button', { name: '创建需求' }))
    expect(await screen.findByText('尚未添加采集来源')).toBeInTheDocument()
    expect(create.mock.calls[1]).toEqual(create.mock.calls[0])
    expect(create.mock.calls[0][1]).toEqual(expect.any(String))
  })

  it('creates an independent requirement without sources', async () => {
    const value = requirement({ sources: [], sourceCount: 0 })
    const create = vi.spyOn(api, 'createCollection').mockResolvedValue(value)
    vi.spyOn(api, 'collection').mockResolvedValue(value)
    mount('/collections/new')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('需求名称'), '全国公共资源交易标讯')
    await user.type(screen.getByLabelText('采集目标'), 'Collect notices')
    await user.click(screen.getByRole('button', { name: '创建需求' }))
    expect(await screen.findByText('尚未添加采集来源')).toBeInTheDocument()
    expect(create.mock.calls[0][0]).toEqual({ name: value.name, intent: value.intent })
  })

  it('keeps edits on failure and submits the captured revision on retry', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    const update = vi.spyOn(api, 'updateCollection').mockRejectedValueOnce(new Error('offline')).mockResolvedValue(requirement({ name: 'Changed', revision: 2 }))
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '编辑基本信息' }))
    await user.clear(screen.getByLabelText('需求名称'))
    await user.type(screen.getByLabelText('需求名称'), 'Changed')
    await user.click(screen.getByRole('button', { name: '保存需求' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.getByLabelText('需求名称')).toHaveValue('Changed')
    await user.click(screen.getByRole('button', { name: '保存需求' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(update.mock.calls[1]).toEqual(['collection_nationwide_tender', { name: 'Changed', intent: 'Collect notices', revision: 1 }])
  })

  it('requires exact name confirmation for deletion and retains the detail when deletion fails', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement({ sources: [], sourceCount: 0 }))
    vi.spyOn(api, 'collectionsPage').mockResolvedValue({ items: [], total: 0, counts: { all: 0, active: 0, archived: 0 }, pagination: { page: 1, pageSize: 50, total: 0, totalPages: 1 } })
    const remove = vi.spyOn(api, 'deleteCollection').mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ id: 'collection_nationwide_tender', deleted: true })
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '删除需求' }))
    expect(screen.getByRole('button', { name: '确认' })).toBeDisabled()
    await user.type(screen.getByLabelText('输入完整需求名称以确认删除'), '全国公共资源交易标讯')
    await user.click(screen.getByRole('button', { name: '确认' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    await user.click(screen.getByRole('button', { name: '确认' }))
    expect(await screen.findByText('尚无采集需求')).toBeInTheDocument()
    expect(remove.mock.calls[1]).toEqual(['collection_nationwide_tender', 1])
  })

  it('archives linked requirements instead of deleting them and supports restore', async () => {
    const read = vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    const update = vi.spyOn(api, 'updateCollection').mockImplementation(async (_id, input) => {
      const value = requirement({ status: input.status ?? 'active', revision: input.revision + 1 })
      read.mockResolvedValue(value)
      return value
    })
    mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '归档需求' }))
    expect(screen.queryByRole('button', { name: '删除需求' })).not.toBeInTheDocument()
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '确认' }))
    await user.click(await screen.findByRole('button', { name: '恢复需求' }))
    expect(await screen.findByRole('button', { name: '编辑基本信息' })).toBeInTheDocument()
    expect(update.mock.calls[1][1]).toEqual({ revision: 2, status: 'active' })
  })

  it('offers explicit reload on a revision conflict and hides mutations for viewers', async () => {
    vi.spyOn(api, 'collection').mockResolvedValue(requirement())
    vi.spyOn(api, 'updateCollection').mockRejectedValue(new ApiRequestError({ code: 'COLLECTION_CONFLICT', message: 'conflict', requestId: 'test', retryable: false }))
    const rendered = mount()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '编辑基本信息' }))
    await user.click(screen.getByRole('button', { name: '保存需求' }))
    expect(await screen.findByRole('button', { name: '放弃编辑并重新加载' })).toBeInTheDocument()
    rendered.unmount()
    vi.spyOn(api, 'authState').mockResolvedValue({ authEnabled: true, authenticated: true, setupRequired: false, user: { id: 'viewer', username: 'viewer', displayName: 'Viewer', role: 'viewer' } })
    mount(undefined, true)
    await screen.findByRole('heading', { name: '全国公共资源交易标讯' })
    expect(screen.queryByRole('button', { name: '编辑基本信息' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '添加来源' })).not.toBeInTheDocument()
  })
})
