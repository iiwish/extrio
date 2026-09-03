import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Outlet, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedCollectors } from '@/api/fixtures'
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

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/collectors/${collectorId}`]}>
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
    await user.click(await screen.findByRole('button', { name: '导出该采集器的签名证据包（ZIP）' }))

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1))
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/zip')
    const evidenceCall = fetchMock.mock.calls.find((call) => String(call[0]).endsWith('/evidence-bundle'))
    expect(evidenceCall).toBeDefined()
    expect(String(evidenceCall![0])).toContain(`/api/v1/collectors/${collectorId}/evidence-bundle`)
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
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
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

    await screen.findByText('该采集器没有可修复的规则')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
