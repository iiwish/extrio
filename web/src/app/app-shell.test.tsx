import { cleanup, render, screen } from '@testing-library/react'
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
            <Route path="collectors/:collectorId" element={<div>采集器详情</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('采集器详情')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '采集器' })).toHaveClass('is-active')
    expect(screen.queryByText('本地验收工作区')).not.toBeInTheDocument()
    expect(screen.getByLabelText('当前页面')).toHaveTextContent('采集器')
    expect(screen.queryByText('北辰数据')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回所属需求' })).toHaveAttribute('href', '/collectors')
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

    expect(screen.getByText('运行详情')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回运行列表' })).toHaveAttribute('href', '/runs')
    expect(screen.getByLabelText('当前页面')).toHaveTextContent('运行')
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

    expect(screen.getByText('数据详情')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回数据列表' })).toHaveAttribute('href', '/items')
    expect(screen.getByLabelText('当前页面')).toHaveTextContent('数据')
  })
})
