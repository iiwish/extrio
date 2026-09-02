import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedAiRuns } from '@/api/fixtures'
import { AiRunPage } from './ai-run-page'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/ai-runs/${seedAiRuns[0].id}`]}>
        <Routes><Route path="/ai-runs/:aiRunId" element={<AiRunPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AiRunPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(seedAiRuns[0]), { headers: { 'Content-Type': 'application/json' } })))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('leads with the source and review outcome while keeping technical ids collapsed', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'https://www.zfcg.sh.gov.cn' })).toBeInTheDocument()
    expect(screen.getByText('候选规则等待审核')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /审核候选规则/ })).toBeInTheDocument()
    expect(screen.queryByText(seedAiRuns[0].operationId)).not.toBeInTheDocument()
  })

  it('shows model usage metadata without exposing prompts or response bodies', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('候选规则等待审核')
    await user.click(screen.getByRole('tab', { name: /模型调用/ }))

    expect(screen.getByText('页面结构发现')).toBeInTheDocument()
    expect(screen.getByText('规则编译')).toBeInTheDocument()
    expect(screen.getByText('不保存原始提示词与响应正文', { exact: false })).toBeInTheDocument()
  })
})
