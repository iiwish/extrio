import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { seedAiRuns, seedCollectors, seedRuns } from '@/api/fixtures'
import { mockAiRunPage, mockCollectionPage, mockCollectorPage, mockRunPage } from '@/api/workspace-mock'
import { requirement } from '@/features/collections/collection-test-data'
import { CollectionsPage } from '@/features/collections/collections-page'
import { CollectorsPage } from '@/features/collectors/collectors-page'
import { RunsPage } from '@/features/runs/runs-page'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
function LocationProbe() { return <output data-testid="location">{useLocation().search}</output> }

it.each(['collections', 'collectors', 'runs', 'ai-runs'])('%s uses the shared bounded list and replaces pages, preserving URL and filter behavior', async kind => {
  const user = userEvent.setup()
  const collections = Array.from({ length: 51 }, (_, index) => requirement({ id: `collection_${index}`, name: `Requirement ${index}` }))
  const collectors = Array.from({ length: 51 }, (_, index) => ({ ...seedCollectors[0], id: `collector_${index}`, name: `Source ${index}` }))
  const runs = Array.from({ length: 51 }, (_, index) => ({ ...seedRuns[0], id: `run_${index}`, collectorName: `Source ${index}` }))
  const aiRuns = Array.from({ length: 51 }, (_, index) => ({ ...seedAiRuns[0], id: `ai_${index}`, collectorName: `Source ${index}` }))
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    const result = kind === 'collections' ? mockCollectionPage(url.searchParams, collections)
      : kind === 'collectors' ? mockCollectorPage(url.searchParams, collectors, runs)
        : kind === 'runs' ? mockRunPage(url.searchParams, runs) : mockAiRunPage(url.searchParams, aiRuns)
    return new Response(JSON.stringify(result), { headers: { 'Content-Type': 'application/json' } })
  }))
  const View = kind === 'collections' ? CollectionsPage : kind === 'collectors' ? CollectorsPage : RunsPage
  const route = kind === 'ai-runs' ? '/runs?view=ai&page=2&pageSize=20' : `/${kind}?page=2&pageSize=20`
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[route]}><View /><LocationProbe /></MemoryRouter></QueryClientProvider>)
  await screen.findByText('第 21–40 行，共 51 行')
  const scroll = document.querySelector('.list-workspace-scroll')!
  expect(scroll.querySelectorAll('a')).toHaveLength(20)
  expect(scroll).not.toContainElement(screen.getByRole('navigation', { name: '列表分页' }))
  const firstPageLinks = [...scroll.querySelectorAll('a')].map(row => row.getAttribute('href')!.split('?')[0])
  scroll.scrollTop = 400
  await user.click(screen.getByRole('button', { name: '下一页' }))
  await screen.findByText('第 41–51 行，共 51 行')
  expect(scroll.querySelectorAll('a')).toHaveLength(11)
  expect([...scroll.querySelectorAll('a')].every(row => !firstPageLinks.includes(row.getAttribute('href')!.split('?')[0]))).toBe(true)
  expect(scroll.scrollTop).toBe(0)
  expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
  expect(screen.getByTestId('location')).toHaveTextContent('page=3')
  await user.selectOptions(screen.getByRole('combobox', { name: '每页行数' }), '50')
  await screen.findByText('第 1–50 行，共 51 行')
  expect(screen.getByTestId('location')).not.toHaveTextContent('page=')
  const searchLabel = kind === 'collections' ? '搜索采集需求' : kind === 'collectors' ? '搜索采集来源' : kind === 'runs' ? '搜索运行' : '搜索 AI 任务'
  await user.type(screen.getByRole('textbox', { name: searchLabel }), 'no-matching-data')
  await screen.findByText('第 0–0 行，共 0 行')
  await waitFor(() => expect(screen.getByRole('spinbutton', { name: '当前页码' })).toHaveValue(1))
})
