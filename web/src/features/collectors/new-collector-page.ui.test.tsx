import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { seedCollectors } from '@/api/fixtures'
import type { BatchCollectorImportResult, CreateCollectorsInput } from '@/api/types'
import { NewCollectorPage } from './new-collector-page'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('shows the published fixed version rather than the legacy collection reference', async () => {
  vi.spyOn(api, 'collections').mockResolvedValue([{id:'chosen',name:'指定需求',intent:'采集公告',status:'active',collectionVersion:'tender_notice_v4',activeVersionId:'colver_frozen',activeVersion:{id:'colver_frozen',versionNumber:2,fieldCount:3,outputContractDigest:'sha256:test',publishedAt:'2026-09-10T00:00:00Z'},sourceCount:0,publishedSourceCount:0,revision:1,createdAt:'2026-09-06T00:00:00Z',updatedAt:'2026-09-06T00:00:00Z'}])
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  const router=createMemoryRouter([{path:'/collectors/new',element:<NewCollectorPage />}],{initialEntries:['/collectors/new?collection=chosen']})
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  expect(await screen.findByText('colver_frozen')).toBeInTheDocument()
  expect(screen.queryByText('tender_notice_v4')).not.toBeInTheDocument()
})

it('keeps the CSV format help compact in an icon tooltip', async () => {
  vi.spyOn(api, 'collections').mockResolvedValue([{id:'chosen',name:'指定需求',intent:'采集公告',status:'active',collectionVersion:'v1',sourceCount:0,publishedSourceCount:0,revision:1,createdAt:'2026-09-06T00:00:00Z',updatedAt:'2026-09-06T00:00:00Z'}])
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  const router=createMemoryRouter([{path:'/collectors/new',element:<NewCollectorPage />}],{initialEntries:['/collectors/new?collection=chosen']})
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  expect(await screen.findByRole('button', {name:'CSV / TXT'})).toBeInTheDocument()
  expect(screen.getByRole('textbox', {name:'手动添加，每行一个具体列表页'})).toBeInTheDocument()
  expect(document.querySelector('#source-format-note')).not.toBeInTheDocument()
})

it('keeps the requested requirement selected when its options load after the form mounts', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof api.collections>>) => void
  vi.spyOn(api, 'collections').mockImplementation(() => new Promise(done => {resolve = done}))
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  const router = createMemoryRouter([{path:'/collectors/new',element:<NewCollectorPage />}], {initialEntries:['/collectors/new?collection=chosen']})
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  await waitFor(() => expect(resolve).toBeTypeOf('function'))
  resolve(['first','chosen'].map(id => ({ id, name:id === 'chosen' ? '指定需求' : '第一个需求', intent:'测试意图', status:'active', collectionVersion:'v1', sourceCount:0, publishedSourceCount:0, revision:1, createdAt:'2026-09-06T00:00:00Z', updatedAt:'2026-09-06T00:00:00Z', fieldDraft:{fields:[]} })))
  const select = await screen.findByRole('combobox', {name:'选择已有需求'})
  await waitFor(() => expect(select).toHaveTextContent('指定需求'))
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', {name:'手动添加，每行一个具体列表页'}), 'https://example.com/list')
  expect(select).toHaveTextContent('指定需求')
  await user.click(screen.getByRole('button',{name:'取消'}))
  expect(await screen.findByRole('dialog',{name:'放弃未保存的来源？'})).toBeInTheDocument()
  await user.click(screen.getByRole('button',{name:'继续编辑'}))
  expect(screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'})).toHaveValue('https://example.com/list')
})

it('retains input on create failure and leaves without a discard prompt after a successful retry', async () => {
  vi.spyOn(api,'collections').mockResolvedValue([{id:'chosen',name:'指定需求',intent:'采集公告',status:'active',collectionVersion:'v1',sourceCount:0,publishedSourceCount:0,revision:1,createdAt:'2026-09-06T00:00:00Z',updatedAt:'2026-09-06T00:00:00Z'}])
  const create=vi.spyOn(api,'createCollectors').mockRejectedValueOnce(new Error('offline')).mockResolvedValue({collectionId:'chosen',collectionName:'指定需求',collectionVersion:'v1',total:1,createdCount:1,rejectedCount:0,results:[{status:'created',error:null,sourceUrl:'https://example.com/notices',collector:{...seedCollectors[0],id:'created'}}]})
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  const router=createMemoryRouter([{path:'/collectors/new',element:<NewCollectorPage />},{path:'/collectors/:id',element:<h1>已创建来源</h1>}],{initialEntries:['/collectors/new?collection=chosen']})
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  const user=userEvent.setup()
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'选择已有需求'})).toHaveTextContent('指定需求'))
  const input=screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'})
  await user.type(input,'https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await within(screen.getByRole('dialog', {name:'新建采集来源'})).findByRole('alert')).toHaveTextContent('offline')
  expect(input).toHaveValue('https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await screen.findByRole('heading',{name:'已创建来源'})).toBeInTheDocument()
  expect(create).toHaveBeenCalledTimes(2)
  expect(create.mock.calls[0][1]).toBeTypeOf('string')
  expect(create.mock.calls[1][1]).toBe(create.mock.calls[0][1])
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

const requirement = {id:'chosen',name:'指定需求',intent:'采集公告',status:'active' as const,collectionVersion:'v1',sourceCount:0,publishedSourceCount:0,revision:1,createdAt:'2026-09-06T00:00:00Z',updatedAt:'2026-09-06T00:00:00Z'}

function createdResult(input: CreateCollectorsInput): BatchCollectorImportResult {
  return {collectionId:'chosen',collectionName:input.collectionName,collectionVersion:'v1',total:1,createdCount:1,rejectedCount:0,results:[{status:'created',error:null,sourceUrl:input.sources[0].entryUrl,collector:{...seedCollectors[0],id:'created'}}]}
}

function rejectedResult(collectionId: string | null): BatchCollectorImportResult {
  return {collectionId,collectionName:'指定需求',collectionVersion:collectionId ? 'v1' : null,total:1,createdCount:0,rejectedCount:1,results:[{status:'rejected',collector:null,sourceUrl:'https://example.com/notices',error:{code:'SOURCE_ALREADY_EXISTS',message:'该 Source URL 已存在',requestId:'test',retryable:false}}]}
}

function renderCreation(existing = true) {
  vi.spyOn(api,'collections').mockResolvedValue(existing ? [requirement] : [])
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  const router = createMemoryRouter([{path:'/collectors/new',element:<NewCollectorPage />},{path:'/collectors/:id',element:<h1>已创建来源</h1>}],{initialEntries:[existing ? '/collectors/new?collection=chosen' : '/collectors/new']})
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  return userEvent.setup()
}

it.each([true,false])('replays a committed creation after response loss (existing requirement: %s)', async existing => {
  let committed: { key: string | undefined; result: BatchCollectorImportResult } | undefined
  const create = vi.spyOn(api,'createCollectors').mockImplementation(async (input, key) => {
    if (!committed) {
      committed = {key,result:createdResult(input)}
      throw new Error('response lost after commit')
    }
    return key === committed.key ? committed.result : rejectedResult(null)
  })
  const user = renderCreation(existing)
  if (existing) await waitFor(()=>expect(screen.getByRole('combobox',{name:'选择已有需求'})).toHaveTextContent('指定需求'))
  else {
    await user.type(await screen.findByRole('textbox',{name:'需求名称'}),'指定需求')
    await user.type(screen.getByRole('textbox',{name:'采集意图'}),'采集公告')
  }
  await user.type(screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'}),'https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await within(screen.getByRole('dialog',{name:'新建采集来源'})).findByRole('alert')).toHaveTextContent('response lost after commit')
  expect(committed?.key).toBeTypeOf('string')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await screen.findByRole('heading',{name:'已创建来源'})).toBeInTheDocument()
  expect(create).toHaveBeenCalledTimes(2)
  expect(create.mock.calls[1][1]).toBe(committed?.key)
})

it('uses a new idempotency key when the payload changes after a failed request', async () => {
  const create = vi.spyOn(api,'createCollectors').mockRejectedValueOnce(new Error('offline')).mockImplementation(async input=>createdResult(input))
  const user = renderCreation()
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'选择已有需求'})).toHaveTextContent('指定需求'))
  const input = screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'})
  await user.type(input,'https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await within(screen.getByRole('dialog',{name:'新建采集来源'})).findByRole('alert')).toHaveTextContent('offline')
  await user.clear(input)
  await user.type(input,'https://example.com/changed-notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await screen.findByRole('heading',{name:'已创建来源'})).toBeInTheDocument()
  expect(create.mock.calls[0][1]).toBeTypeOf('string')
  expect(create.mock.calls[1][1]).toBeTypeOf('string')
  expect(create.mock.calls[1][1]).not.toBe(create.mock.calls[0][1])
})

it('does not submit a second command while creation is pending', async () => {
  let complete!: (value: BatchCollectorImportResult) => void
  const create = vi.spyOn(api,'createCollectors').mockImplementation(()=>new Promise(resolve=>{complete=resolve}))
  const user = renderCreation()
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'选择已有需求'})).toHaveTextContent('指定需求'))
  await user.type(screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'}),'https://example.com/notices')
  const submit = screen.getByRole('button',{name:'创建 1 个采集来源'})
  await user.dblClick(submit)
  expect(submit).toBeDisabled()
  expect(screen.getByRole('button',{name:'取消'})).toBeDisabled()
  expect(create).toHaveBeenCalledTimes(1)
  complete(createdResult(create.mock.calls[0][0]))
  expect(await screen.findByRole('heading',{name:'已创建来源'})).toBeInTheDocument()
})

it('shows no created requirement or detail link when every new-requirement source is rejected', async () => {
  const create = vi.spyOn(api,'createCollectors').mockResolvedValue(rejectedResult(null))
  const user = renderCreation(false)
  await user.type(await screen.findByRole('textbox',{name:'需求名称'}),'指定需求')
  await user.type(screen.getByRole('textbox',{name:'采集意图'}),'采集公告')
  await user.type(screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'}),'https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await screen.findByRole('heading',{name:'未创建采集来源'})).toBeInTheDocument()
  expect(screen.getByText('未创建采集需求')).toBeInTheDocument()
  expect(screen.getAllByText('该 Source URL 已存在').length).toBeGreaterThan(0)
  expect(screen.queryByRole('link',{name:'查看需求明细'})).not.toBeInTheDocument()
  await user.click(screen.getByRole('button',{name:'继续导入'}))
  await user.type(screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'}),'https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await screen.findByRole('heading',{name:'未创建采集来源'})).toBeInTheDocument()
  expect(create.mock.calls[0][1]).toBeTypeOf('string')
  expect(create.mock.calls[1][1]).not.toBe(create.mock.calls[0][1])
})

it('retains the real requirement link after every source for an existing requirement is rejected', async () => {
  vi.spyOn(api,'createCollectors').mockResolvedValue(rejectedResult('chosen'))
  const user = renderCreation()
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'选择已有需求'})).toHaveTextContent('指定需求'))
  await user.type(screen.getByRole('textbox',{name:'手动添加，每行一个具体列表页'}),'https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await screen.findByRole('heading',{name:'未创建采集来源'})).toBeInTheDocument()
  expect(screen.getByRole('link',{name:'查看需求明细'})).toHaveAttribute('href','/collections/chosen')
  expect(screen.queryByText('未创建采集需求')).not.toBeInTheDocument()
})
