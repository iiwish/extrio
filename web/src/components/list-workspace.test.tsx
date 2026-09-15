import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { ListWorkspace } from './list-workspace'

afterEach(cleanup)

it('keeps toolbar, count and pagination outside the scrolling rows', () => {
  render(<ListWorkspace label="Results" count={20} total={80} toolbar={<button>Search</button>} footer={<button>Load more</button>}><p>Record</p></ListWorkspace>)
  const scroll = screen.getByRole('region', { name: 'Results' })
  expect(scroll).toContainElement(screen.getByText('Record'))
  expect(scroll).not.toContainElement(screen.getByRole('button', { name: 'Search' }))
  expect(scroll).not.toContainElement(screen.getByRole('button', { name: 'Load more' }))
  expect(screen.getByRole('status')).toHaveTextContent('20 / 80')
  expect(scroll).toHaveAttribute('tabindex', '0')
})

it('does not interpret unknown totals as zero or a complete count', () => {
  const { rerender } = render(<ListWorkspace label="Results" toolbar={null} loading><p /></ListWorkspace>)
  expect(screen.getByRole('status')).toHaveTextContent('加载中')
  rerender(<ListWorkspace label="Results" toolbar={null} failed><p /></ListWorkspace>)
  expect(screen.getByRole('status')).toHaveTextContent('数量不可用')
  expect(screen.getByRole('status')).not.toHaveTextContent('0')
  rerender(<ListWorkspace label="Results" toolbar={null} count={20} partial><p /></ListWorkspace>)
  expect(screen.getByRole('status')).toHaveTextContent('已加载 20 条')
})

it('can hide the inline count when pagination already provides the range', () => {
  render(<ListWorkspace label="Results" showSummary={false} count={20} toolbar={<button>Search</button>}><p>Record</p></ListWorkspace>)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('keeps a stale count distinguishable from a successful refresh and resets only for changed filters', () => {
  const { rerender } = render(<ListWorkspace label="Results" toolbar={null} count={3} resetKey="all"><p /></ListWorkspace>)
  const scroll = screen.getByRole('region', { name: 'Results' })
  scroll.scrollTop = 400
  rerender(<ListWorkspace label="Results" toolbar={null} count={3} failed resetKey="all"><p /></ListWorkspace>)
  expect(screen.getByRole('status')).toHaveTextContent('未刷新')
  expect(scroll.scrollTop).toBe(400)
  rerender(<ListWorkspace label="Results" toolbar={null} count={1} resetKey="filtered"><p /></ListWorkspace>)
  expect(scroll.scrollTop).toBe(0)
})
