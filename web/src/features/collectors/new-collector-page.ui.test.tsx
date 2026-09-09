import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { seedCollectors } from '@/api/fixtures'
import { NewCollectorPage } from './new-collector-page'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

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
  await user.click(screen.getByRole('link',{name:'取消'}))
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
  expect(await screen.findByRole('alert')).toHaveTextContent('offline')
  expect(input).toHaveValue('https://example.com/notices')
  await user.click(screen.getByRole('button',{name:'创建 1 个采集来源'}))
  expect(await screen.findByRole('heading',{name:'已创建来源'})).toBeInTheDocument()
  expect(create).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
