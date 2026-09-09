import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { CollectorPage } from './collector-page'

vi.mock('@/features/auth/auth-gate', () => ({useAuth: () => ({user:{role:'viewer'}})}))
afterEach(() => {cleanup(); vi.restoreAllMocks()})

it('shows abnormal latest-run state without offering a read-only user execution controls', async () => {
  const collector = {...seedCollectors[0],status:'published' as const,latestRunId:'last'}
  vi.spyOn(api,'collector').mockResolvedValue(collector)
  vi.spyOn(api,'runDetail').mockResolvedValue({...seedRuns[0],id:'last',status:'partially_succeeded',summary:'详情抓取不完整'})
  vi.spyOn(api,'aiRuns').mockResolvedValue([])
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/collectors/source?returnTo=%2Fruns%3Fview%3Dai']}><Routes><Route element={<Outlet context={{setTopbarBackTarget:vi.fn()}} />}><Route path="/collectors/:collectorId" element={<CollectorPage />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('heading',{name:'最近运行需要处理'})).toBeInTheDocument()
  expect(screen.getByRole('button',{name:'立即运行'})).toBeDisabled()
  await userEvent.setup().click(screen.getByRole('tab',{name:'采集配置'}))
  expect(screen.getByRole('button',{name:'编辑'})).toBeDisabled()
})

it('displays contract coverage and missing requirement fields gap in review workspace', async () => {
  const collector = {
    ...seedCollectors[0],
    status: 'ready_review' as const,
    collectionFields: [
      { key: 'title', label: '标题', type: 'string' as const, required: true, identity: false, fingerprint: true, description: '' },
      { key: 'buyer', label: '采购单位', type: 'string' as const, required: true, identity: false, fingerprint: true, description: '' },
      { key: 'optionalMissing', label: '缺失选填字段', type: 'number' as const, required: false, identity: false, fingerprint: true, description: '' },
      { key: 'requiredMissing', label: '缺失必填字段', type: 'string' as const, required: true, identity: false, fingerprint: true, description: '' },
    ],
  }
  vi.spyOn(api, 'collector').mockResolvedValue(collector)
  vi.spyOn(api, 'aiRuns').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/collectors/source?section=rule']}>
        <Routes>
          <Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}>
            <Route path="/collectors/:collectorId" element={<CollectorPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
  expect(await screen.findByText(/1 个必填需求字段缺失/)).toBeInTheDocument()
  expect(screen.getByText('需求未覆盖字段（契约缺口）')).toBeInTheDocument()
  expect(screen.getByText('缺失选填字段')).toBeInTheDocument()
  expect(screen.getAllByText('缺失必填字段')).toHaveLength(2)
  expect(screen.getByText('安全 (选填缺口)')).toBeInTheDocument()
  expect(screen.getByText('阻断 (必填缺失)')).toBeInTheDocument()
})
