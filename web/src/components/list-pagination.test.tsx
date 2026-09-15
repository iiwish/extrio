import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ListPagination } from './list-pagination'

afterEach(cleanup)

it('supports first, previous, next, last, and explicit page jumps', async () => {
  const user = userEvent.setup()
  const onPageChange = vi.fn()
  render(<ListPagination page={3} pageSize={50} total={206} totalPages={5} onPageChange={onPageChange} onPageSizeChange={vi.fn()} />)
  expect(screen.getByText('第 101–150 行，共 206 行')).toBeInTheDocument()
  for (const label of ['首页', '上一页', '下一页', '末页']) await user.click(screen.getByRole('button', { name: label }))
  expect(onPageChange.mock.calls).toEqual([[1], [2], [4], [5]])
  const input = screen.getByRole('spinbutton', { name: '当前页码' })
  await user.clear(input)
  await user.type(input, '2{Enter}')
  expect(onPageChange).toHaveBeenLastCalledWith(2)
  await user.clear(input)
  await user.type(input, '99{Enter}')
  expect(onPageChange).toHaveBeenCalledTimes(5)
})

it('keeps empty results at page one and disables all page navigation', () => {
  render(<ListPagination page={1} pageSize={50} total={0} totalPages={1} onPageChange={vi.fn()} onPageSizeChange={vi.fn()} />)
  expect(screen.getByText('第 0–0 行，共 0 行')).toBeInTheDocument()
  for (const label of ['首页', '上一页', '下一页', '末页']) expect(screen.getByRole('button', { name: label })).toBeDisabled()
})

it('does not invent counts and locks navigation during pending queries', () => {
  const { rerender } = render(<ListPagination page={1} pageSize={50} pending onPageChange={vi.fn()} onPageSizeChange={vi.fn()} />)
  expect(screen.getByText('行数与页数待确认')).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '每页行数' })).toBeDisabled()
  expect(screen.getByRole('spinbutton')).toBeDisabled()
  rerender(<ListPagination page={1} pageSize={50} total={206} totalPages={5} pending onPageChange={vi.fn()} onPageSizeChange={vi.fn()} />)
  expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
})
