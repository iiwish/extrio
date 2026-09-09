import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { AppShell } from './app-shell'

describe('AppShell navigation', () => {
  afterEach(cleanup)

  it('returns from a detail route to the workspace home through the brand', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/collectors/collector_beijing_tender']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>运营主页</div>} />
            <Route path="collectors/:collectorId" element={<div>采集来源详情</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    expect(within(screen.getByRole('main')).getByText('采集来源详情')).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: '主导航' })).getByRole('link', { name: '采集来源' })).toHaveClass('is-active')
    expect(screen.queryByText('本地验收工作区')).not.toBeInTheDocument()
    expect(screen.getByLabelText('当前页面')).toHaveTextContent('采集来源')
    expect(screen.queryByText('北辰数据')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回采集来源列表' })).toHaveAttribute('href', '/collectors')
    expect(screen.queryByText('返回所属需求')).not.toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Extrio 首页' }))

    expect(screen.getByText('运营主页')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '概览' })).toHaveClass('is-active')
  })

  it('places the run-detail return action in the top bar', () => {
    render(
      <MemoryRouter initialEntries={['/runs/run_0842']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="runs/:runId" element={<div>运行详情</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    expect(within(screen.getByRole('main')).getByText('运行详情')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回运行列表' })).toHaveAttribute('href', '/runs')
    expect(screen.getByLabelText('当前页面')).toHaveTextContent('运行')
    expect(within(screen.getByLabelText('当前页面')).getByText('运行详情')).toHaveAttribute('aria-current', 'page')
  })

  it('places the item-detail return action in the top bar', () => {
    render(
      <MemoryRouter initialEntries={['/items/item_0842']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="items/:itemId" element={<div>数据详情</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    expect(within(screen.getByRole('main')).getByText('数据详情')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回数据列表' })).toHaveAttribute('href', '/items')
    expect(screen.getByLabelText('当前页面')).toHaveTextContent('数据')
  })

  it('places the new-collector context and collection-aware return action in the top bar', () => {
    render(
      <MemoryRouter initialEntries={['/collectors/new?collection=collection_procurement']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="collectors/new" element={<div>新建表单</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    const currentPage = screen.getByLabelText('当前页面')
    expect(screen.getByText('新建表单')).toBeInTheDocument()
    expect(within(currentPage).getByRole('link', { name: '返回所属需求' })).toHaveAttribute('href', '/collections/collection_procurement')
    expect(within(currentPage).getByRole('link', { name: '采集需求' })).toHaveAttribute('href', '/collections/collection_procurement')
    expect(within(currentPage).getByRole('link', { name: '采集需求' })).not.toHaveAttribute('aria-current')
    expect(within(currentPage).getByText('新建采集来源')).toHaveAttribute('aria-current', 'page')
  })
})
