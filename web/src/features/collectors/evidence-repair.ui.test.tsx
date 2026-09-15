import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Outlet, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedAiRuns, seedCollectors } from '@/api/fixtures'
import { CollectorPage } from './collector-page'

vi.stubGlobal('ResizeObserver', class {
  observe() { return undefined }
  unobserve() { return undefined }
  disconnect() { return undefined }
})

const collectorId = 'collector_beijing_tender'

const operationQueued = {
  id: 'op_repair_1',
  kind: 'explore',
  status: 'queued',
  phase: 'queued',
  progress: 6,
  resourceType: 'collector',
  resourceId: collectorId,
  statusUrl: '/api/v1/operations/op_repair_1',
  pollAfterMs: 10,
  metrics: {
    listPagesFetched: 0,
    detailUrlsDiscovered: 0,
    detailPagesFetched: 0,
    recordsOutsideWindow: 0,
    duplicateDetailUrls: 0,
    newItems: 0,
    updatedItems: 0,
    unchangedItems: 0,
    warningCount: 0,
  },
  error: null,
}
const operationSucceeded = { ...operationQueued, status: 'succeeded', phase: 'completed', progress: 100 }

interface RepairCall {
  idempotencyKey: string | null
  body: { note?: string } | null
}

interface ExplorationCall {
  idempotencyKey: string | null
  body: { guidance?: string } | null
}

function jsonResponse(data: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

function evidenceZipResponse() {
  const zip = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0, 0, 0, 0, 0])
  return new Response(zip, {
    status: 200,
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="extrio-evidence-${collectorId}.zip"`,
    },
  })
}

function renderPage(section?: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/collectors/${collectorId}${section ? `?section=${section}` : ''}`]}>
        <Routes>
          <Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}>
            <Route path="collectors/:collectorId" element={<CollectorPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Collector evidence bundle and AI repair', () => {
  let repairCalls: RepairCall[]

  beforeEach(() => {
    repairCalls = []
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:mock-evidence'), revokeObjectURL: vi.fn() })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each(['explore', 'run'])('opens %s logs by default, stays collapsed across polling, and retains failure details', async (kind) => {
    const collector = { ...structuredClone(seedCollectors[0]), latestRunId: null, status: kind === 'explore' ? 'exploring' : 'published', activeOperationId: operationQueued.id }
    let failed = false
    let polls = 0
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path === operationQueued.statusUrl) {
        polls += 1
        return jsonResponse(failed ? { ...operationQueued, kind, status: 'failed', phase: 'completed', error: { code: 'SOURCE_NETWORK_REJECTED', message: '来源页面加载超时', requestId: 'request_timeout', retryable: true, details: { reason: 'browser_navigation_timed_out' } } } : { ...operationQueued, kind })
      }
      return jsonResponse({}, 404)
    }))
    renderPage()
    const user = userEvent.setup()
    const dialog = await screen.findByRole('dialog', { name: '执行日志' })
    expect(within(dialog).getByRole('progressbar')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '收起' }))
    const before = polls
    await waitFor(() => expect(polls).toBeGreaterThan(before))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    failed = true
    await user.click(screen.getByRole('button', { name: '查看执行日志' }))
    await screen.findByText('来源页面加载超时，自动重试后仍未完成。请稍后重试当前任务。')
    expect(within(screen.getByRole('dialog')).getByText('browser_navigation_timed_out')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '收起' }))
    expect(screen.queryByText(/来源页面加载超时/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '查看执行日志' })).toBeInTheDocument()
  })

  it('keeps historical logs collapsed after reload and opens a new task automatically', async () => {
    const collector = { ...structuredClone(seedCollectors[0]), status: 'draft', candidate: null, activeOperationId: null, latestRunId: null }
    const history = { ...structuredClone(seedAiRuns[0]), collectorId, operationId: 'op_previous' }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [history], page: { nextCursor: null } })
      if (path === '/api/v1/operations/op_previous') return jsonResponse({ ...operationSucceeded, id: 'op_previous' })
      if (path.endsWith('/explorations')) return jsonResponse(operationQueued, 202)
      if (path === operationQueued.statusUrl) return jsonResponse(operationSucceeded)
      return jsonResponse({}, 404)
    }))
    renderPage()
    const user = userEvent.setup()
    await screen.findByRole('button', { name: '查看执行日志' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看执行日志' }))
    expect(screen.getByText('op_previous')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '收起' }))
    await user.click(screen.getByRole('button', { name: '生成候选规则' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '开始生成' }))
    await screen.findByRole('dialog', { name: '执行日志' })
    expect(screen.getByText(operationQueued.id)).toBeInTheDocument()
  })

  it('offers targeted repair beside a warning without accepting risk or excluding the field', async () => {
    const collector = { ...structuredClone(seedCollectors[0]), status: 'ready_review' }
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path.endsWith('/repairs')) {
        repairCalls.push({ idempotencyKey: new Headers(init?.headers).get('Idempotency-Key'), body: JSON.parse(String(init?.body)) })
        return jsonResponse(operationQueued, 202)
      }
      if (path === operationQueued.statusUrl) return jsonResponse(operationSucceeded)
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage('rule')
    const user = userEvent.setup()
    const repairButton = await screen.findByRole('button', { name: '让 AI 修复字段 budget' })
    expect(screen.getByText(/不代表来源网页没有该内容/)).toBeInTheDocument()
    expect(screen.getByText(/排除后该字段不再输出/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '审核并发布' })).toBeDisabled()
    await user.click(repairButton)
    const dialog = await screen.findByRole('dialog')
    const note = within(dialog).getByRole('textbox', { name: '修复原因（可选）' })
    expect((note as HTMLTextAreaElement).value).toContain('budget')
    expect((note as HTMLTextAreaElement).value).toContain('25% 的详情页未披露预算')
    expect((note as HTMLTextAreaElement).value).toContain('保留')
    await user.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(repairCalls).toHaveLength(0)
    await user.click(repairButton)
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '启动修复' }))
    await waitFor(() => expect(repairCalls).toHaveLength(1))
    expect(repairCalls[0].body?.note).toContain('budget')
    expect(repairCalls[0].idempotencyKey).toBeTruthy()
    expect(fetchMock.mock.calls.some(([url]) => /publish|candidate/.test(String(url)))).toBe(false)
  })

  it('retains targeted repair guidance after a failed request', async () => {
    const collector = { ...structuredClone(seedCollectors[0]), status: 'ready_review' }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path.endsWith('/repairs')) return jsonResponse({ code: 'REPAIR_FAILED', message: '修复请求暂时失败', requestId: 'req_test', retryable: true }, 503)
      return jsonResponse({}, 404)
    }))
    renderPage('rule')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '让 AI 修复字段 budget' }))
    const note = screen.getByRole('textbox', { name: '修复原因（可选）' })
    await user.clear(note)
    await user.type(note, 'budget：保留原字段，检查金额区域。')
    await user.click(screen.getByRole('button', { name: '启动修复' }))
    await screen.findByText('修复请求暂时失败')
    await user.click(screen.getByRole('button', { name: '让 AI 修复字段 budget' }))
    expect(screen.getByRole('textbox', { name: '修复原因（可选）' })).toHaveValue('budget：保留原字段，检查金额区域。')
  })

  it('disables targeted repair on an archived source', async () => {
    const collector = { ...structuredClone(seedCollectors[0]), status: 'ready_review', lifecycle: 'archived' }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      return jsonResponse({}, 404)
    }))
    renderPage('rule')
    expect(await screen.findByRole('button', { name: '让 AI 修复字段 budget' })).toBeDisabled()
  })

  it('downloads the evidence bundle ZIP through the blob path', async () => {
    const collector = structuredClone(seedCollectors[0])
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path.endsWith('/evidence-bundle')) {
        expect(new Headers(init?.headers).get('Accept')).toBe('application/zip')
        return evidenceZipResponse()
      }
      return jsonResponse({ message: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '导出该采集来源的签名证据包（ZIP）' }))

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1))
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/zip')
    const evidenceCall = fetchMock.mock.calls.find((call) => String(call[0]).endsWith('/evidence-bundle'))
    expect(evidenceCall).toBeDefined()
    expect(String(evidenceCall![0])).toContain(`/api/v1/collectors/${collectorId}/evidence-bundle`)
  })

  it('starts rule generation with one-run guidance instead of opening a chat', async () => {
    const collector = {
      ...structuredClone(seedCollectors[0]),
      status: 'draft' as const,
      candidate: null,
      previewItems: [],
    }
    const explorationCalls: ExplorationCall[] = []
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}` && init?.method !== 'POST') return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path === `/api/v1/collectors/${collectorId}/explorations`) {
        explorationCalls.push({
          idempotencyKey: new Headers(init?.headers).get('Idempotency-Key'),
          body: JSON.parse(String(init?.body)) as { guidance?: string },
        })
        return jsonResponse(operationQueued, 202, { Location: operationQueued.statusUrl })
      }
      if (path === operationQueued.statusUrl) return jsonResponse(operationSucceeded)
      return jsonResponse({ message: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '生成候选规则' }))

    expect(await screen.findByRole('dialog')).toHaveTextContent('结果必须经过人工审核才能发布')
    await user.type(screen.getByLabelText('本次希望 AI 重点关注什么（可选）'), '标题在公告名称列。')
    await user.click(screen.getByRole('button', { name: '开始生成' }))

    await waitFor(() => expect(explorationCalls).toHaveLength(1))
    expect(explorationCalls[0].idempotencyKey).toBeTruthy()
    expect(explorationCalls[0].body).toEqual({ guidance: '标题在公告名称列。' })
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('starts the AI rule repair with the note and refreshes the collector after the operation', async () => {
    const collector = structuredClone(seedCollectors[0])
    let collectorFetches = 0
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) {
        collectorFetches += 1
        return jsonResponse(collector)
      }
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path === `/api/v1/collectors/${collectorId}/repairs`) {
        repairCalls.push({
          idempotencyKey: new Headers(init?.headers).get('Idempotency-Key'),
          body: JSON.parse(String(init?.body)) as { note?: string },
        })
        return jsonResponse(operationQueued, 202, { Location: operationQueued.statusUrl })
      }
      if (path === operationQueued.statusUrl) return jsonResponse(operationSucceeded)
      if (path.endsWith('/evidence-bundle')) return evidenceZipResponse()
      return jsonResponse({ message: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '启动 AI 规则修复' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('修复保留原数据契约')
    await user.type(screen.getByLabelText('修复原因（可选）'), '站点改版')
    await user.click(screen.getByRole('button', { name: '启动修复' }))

    await waitFor(() => expect(repairCalls).toHaveLength(1))
    expect(repairCalls[0].idempotencyKey).toBeTruthy()
    expect(repairCalls[0].body).toEqual({ note: '站点改版' })
    await waitFor(() => expect(collectorFetches).toBeGreaterThanOrEqual(2))
    expect(screen.getByRole('dialog', { name: '执行日志' })).toBeInTheDocument()
    expect(screen.getByText('执行完成')).toBeInTheDocument()
    expect(screen.queryByText('操作未完成')).not.toBeInTheDocument()
  })

  it('maps REPAIR_NOT_APPLICABLE to the localized blocker message', async () => {
    const collector = structuredClone(seedCollectors[0])
    const fetchMock = vi.fn(async (input: string | URL | Request, _init?: RequestInit) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path === `/api/v1/collectors/${collectorId}/repairs`) {
        return jsonResponse({ code: 'REPAIR_NOT_APPLICABLE', message: 'Collector 尚无可修复的规则', requestId: 'req_test', retryable: false }, 409)
      }
      if (path.endsWith('/evidence-bundle')) return evidenceZipResponse()
      return jsonResponse({ message: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '启动 AI 规则修复' }))
    await user.click(await screen.findByRole('button', { name: '启动修复' }))

    await screen.findByText('该采集来源没有可修复的规则')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('explains how to recover when a queued operation has not been claimed', async () => {
    const collector = {
      ...structuredClone(seedCollectors[0]),
      status: 'exploring' as const,
      activeOperationId: operationQueued.id,
    }
    const stalledOperation = { ...operationQueued, queuedAt: '2026-09-04T00:00:00Z' }
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === `/api/v1/collectors/${collectorId}`) return jsonResponse(collector)
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      if (path === stalledOperation.statusUrl) return jsonResponse(stalledOperation)
      return jsonResponse({ message: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByText('等待 Worker 超时')).toBeInTheDocument()
    expect(screen.getByText(/extrio-worker 正在运行/)).toBeInTheDocument()
  })
})
