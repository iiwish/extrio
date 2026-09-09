import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, ApiRequestError } from '@/api/client'
import type { CollectionField } from '@/api/types'
import { CollectionFields, mergeSourceFields } from './collection-fields'
import { requirement } from './collection-test-data'

const title: CollectionField = { key: 'title', label: '标题', type: 'string', required: true, identity: true, fingerprint: true, description: '公告标题' }
const value = requirement({ sourceContracts: [{ sourceId: 'source', sourceName: '采购网站', state: 'published', ruleVersion: 'rule_v1', fields: [title], schema: {}, quality: {} }] })
it('merges source output by field key without duplicating shared fields', () => {
  const first = value.sourceContracts![0]
  expect(mergeSourceFields([first, { ...first, sourceId: 'other', fields: [{ ...title, required: false }, { ...title, key: 'amount' }] }]).map((field) => field.key)).toEqual(['title', 'amount'])
})
function mount(edit = true, data = value) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><CollectionFields requirement={data} canEdit={edit} /></MemoryRouter></QueryClientProvider>)
}
beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('previews actual output fields even before a requirement draft exists', () => {
  mount(false)
  expect(screen.getByText('title')).toBeInTheDocument()
  expect(screen.getByText('来源字段汇总')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '编辑字段' })).not.toBeInTheDocument()
})

it('edits, adds, removes and saves field requirements without discarding failed edits', async () => {
  const update = vi.spyOn(api, 'updateCollection').mockRejectedValueOnce(new Error('offline')).mockResolvedValue(value)
  mount()
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '编辑字段' }))
  await user.click(screen.getByRole('button', { name: '编辑字段 标题' }))
  await user.clear(screen.getByLabelText('字段名称'))
  await user.type(screen.getByLabelText('字段名称'), '公告名称')
  await user.click(screen.getByRole('button', { name: '确认字段' }))
  await user.click(screen.getByRole('button', { name: '添加字段' }))
  await user.type(screen.getByLabelText('字段名称'), '金额')
  await user.type(screen.getByLabelText('字段标识'), 'title')
  expect(screen.getByRole('button', { name: '确认字段' })).toBeDisabled()
  await user.clear(screen.getByLabelText('字段标识'))
  await user.type(screen.getByLabelText('字段标识'), 'amount')
  await user.click(screen.getByRole('button', { name: '确认字段' }))
  await user.click(screen.getByRole('button', { name: '移除字段 公告名称' }))
  expect(screen.queryByText('title')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '撤销移除' }))
  await user.click(screen.getByRole('button', { name: '保存字段草稿' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  expect(screen.getByText('amount')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '保存字段草稿' }))
  expect(await screen.findByRole('status')).toHaveTextContent('字段草稿已保存')
  expect(update.mock.calls[1][1]).toMatchObject({ revision: 1, fieldDraft: { fields: [{ ...title, label: '公告名称' }, { key: 'amount', label: '金额' }] } })
})

it('cancels changes without a server write and keeps schema evidence read-only', async () => {
  const update = vi.spyOn(api, 'updateCollection')
  const mounted = mount()
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '编辑字段' }))
  await user.click(screen.getByRole('button', { name: '移除字段 标题' }))
  await user.click(screen.getByRole('button', { name: '取消' }))
  expect(screen.getByText('title')).toBeInTheDocument()
  expect(update).not.toHaveBeenCalled()
  mounted.unmount()
  mount(false)
  expect(within(screen.getByRole('table')).getByRole('cell', { name: /标题title 公告标题/ })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '查看 标题 的来源' }))
  expect(screen.getByRole('link', { name: '采购网站' })).toHaveAttribute('href', '/collectors/source')
  await waitFor(() => expect(screen.queryByRole('button', { name: '编辑字段' })).not.toBeInTheDocument())
})

it('respects an intentionally empty draft and exposes differences from actual source fields', async () => {
  const mounted = mount(true, { ...value, fieldDraft: { fields: [] } })
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '尚未定义字段' })).toBeInTheDocument()
  mounted.unmount()
  mount(false, { ...value, fieldDraft: { fields: [{ ...title, type: 'url' }, { ...title, key: 'amount', label: '金额' }] } })
  expect(screen.getByRole('button', { name: '查看 标题 的来源' })).toHaveTextContent('有差异')
  await userEvent.setup().click(screen.getByRole('button', { name: '查看 金额 的来源' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('该来源不输出此字段')
})

it('shows shared fields once and inspects source-specific constraints on demand', async () => {
  const first = value.sourceContracts![0]
  mount(false, { ...value, sourceCount: 2, sourceContracts: [first, { ...first, sourceId: 'other', sourceName: '另一网站', fields: [{ ...title, required: false, identity: false }] }] })
  expect(screen.getAllByText('title')).toHaveLength(1)
  expect(screen.getAllByRole('table')).toHaveLength(1)
  expect(screen.getByRole('cell', { name: '依来源而异' })).toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole('button', { name: '查看 标题 的来源' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText(/文本 · 必填/)).toBeInTheDocument()
  expect(within(dialog).getByText(/文本 · 选填/)).toBeInTheDocument()
})

it('keeps the local fields and captured revision after a conflict until explicit discard', async () => {
  const update = vi.spyOn(api, 'updateCollection').mockRejectedValue(new ApiRequestError({ code: 'COLLECTION_CONFLICT', message: 'conflict', requestId: 'conflict-test', retryable: false }))
  mount()
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '编辑字段' }))
  await user.click(screen.getByRole('button', { name: '移除字段 标题' }))
  await user.click(screen.getByRole('button', { name: '保存字段草稿' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('conflict')
  expect(screen.queryByText('title')).not.toBeInTheDocument()
  expect(update.mock.calls[0][1]).toEqual({ revision: 1, fieldDraft: { fields: [] } })
  await user.click(screen.getByRole('button', { name: '放弃草稿并重新加载' }))
  expect(screen.getByText('title')).toBeInTheDocument()
  expect(update).toHaveBeenCalledTimes(1)
})

it('restores keyboard focus after inspecting or editing a field and clears the unload guard on cancel', async () => {
  mount()
  const user = userEvent.setup()
  const inspect = screen.getByRole('button', { name: '查看 标题 的来源' })
  await user.click(inspect)
  await user.keyboard('{Escape}')
  await waitFor(() => expect(inspect).toHaveFocus())
  await user.click(screen.getByRole('button', { name: '编辑字段' }))
  const edit = screen.getByRole('button', { name: '编辑字段 标题' })
  await user.click(edit)
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '取消' }))
  await waitFor(() => expect(edit).toHaveFocus())
  const guarded = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(guarded)
  expect(guarded.defaultPrevented).toBe(true)
  await user.click(screen.getByRole('button', { name: '取消' }))
  const unguarded = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(unguarded)
  expect(unguarded.defaultPrevented).toBe(false)
})

it('generates requirement fields from source with replace or merge mode', async () => {
  const extraField: CollectionField = { key: 'content', label: '正文', type: 'html', required: false, identity: false, fingerprint: true, description: '' }
  const sourceWithMultiple = {
    ...value.sourceContracts![0],
    fields: [title, extraField],
  }
  mount(true, {
    ...value,
    sourceContracts: [sourceWithMultiple],
    fieldDraft: { fields: [{ ...title, key: 'custom_old' }] },
  })
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '根据来源生成字段' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('根据来源生成字段')
  await user.click(screen.getByRole('button', { name: '应用并生成' }))
  expect(screen.getByText('title')).toBeInTheDocument()
  expect(screen.getByText('content')).toBeInTheDocument()
  expect(screen.queryByText('custom_old')).not.toBeInTheDocument()
})
