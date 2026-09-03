import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { seedCollectors } from '@/api/fixtures'
import type { DeliveryAttempt, DeliverySummary, Sink, SinkInput, SinkUpdateInput } from '@/api/types'
import { CollectorPage } from './collector-page'

const collectorId = 'collector_beijing_tender'

const sinks: Sink[] = [{
  id: 'sink_beijing_webhook',
  collectorId,
  type: 'webhook',
  url: 'https://hooks.example.com/extrio/beijing',
  enabled: true,
  version: 1,
  credentialConfigured: true,
  createdAt: '2026-08-30T02:00:00.000Z',
  updatedAt: '2026-08-30T02:00:00.000Z',
}]

const deliveries: DeliverySummary[] = [
  {
    id: 'delivery_beijing_0902_a',
    collectorId,
    sinkId: 'sink_beijing_webhook',
    sinkVersionId: 'sink_beijing_webhook#v1',
    itemEventId: 'evt_20260902_0007',
    status: 'delivered',
    attemptCount: 2,
    nextAttemptAt: null,
    leaseUntil: null,
    lastStatusCode: 200,
    lastError: null,
    redeliveryCount: 0,
    createdAt: '2026-09-02T09:12:00.000Z',
    updatedAt: '2026-09-02T09:12:41.000Z',
    latestAttempt: {
      id: 'attempt_beijing_0902_a_2',
      deliveryId: 'delivery_beijing_0902_a',
      attemptNo: 2,
      startedAt: '2026-09-02T09:12:39.000Z',
      finishedAt: '2026-09-02T09:12:41.000Z',
      statusCode: 200,
      error: null,
    },
  },
  {
    id: 'delivery_beijing_0902_b',
    collectorId,
    sinkId: 'sink_beijing_webhook',
    sinkVersionId: 'sink_beijing_webhook#v1',
    itemEventId: 'evt_20260902_0011',
    status: 'failed',
    attemptCount: 1,
    nextAttemptAt: '2026-09-03T02:30:00.000Z',
    leaseUntil: null,
    lastStatusCode: 502,
    lastError: 'upstream connect error',
    redeliveryCount: 0,
    createdAt: '2026-09-02T11:40:00.000Z',
    updatedAt: '2026-09-02T11:40:18.000Z',
    latestAttempt: {
      id: 'attempt_beijing_0902_b_1',
      deliveryId: 'delivery_beijing_0902_b',
      attemptNo: 1,
      startedAt: '2026-09-02T11:40:16.000Z',
      finishedAt: '2026-09-02T11:40:18.000Z',
      statusCode: 502,
      error: 'upstream connect error',
    },
  },
  {
    id: 'delivery_beijing_0901_c',
    collectorId,
    sinkId: 'sink_beijing_webhook',
    sinkVersionId: 'sink_beijing_webhook#v1',
    itemEventId: 'evt_20260901_0003',
    status: 'dead_lettered',
    attemptCount: 3,
    nextAttemptAt: null,
    leaseUntil: null,
    lastStatusCode: null,
    lastError: 'ECONNREFUSED 203.0.113.9:443',
    redeliveryCount: 1,
    createdAt: '2026-09-01T15:02:00.000Z',
    updatedAt: '2026-09-01T15:33:52.000Z',
    latestAttempt: {
      id: 'attempt_beijing_0901_c_3',
      deliveryId: 'delivery_beijing_0901_c',
      attemptNo: 3,
      startedAt: '2026-09-01T15:33:50.000Z',
      finishedAt: '2026-09-01T15:33:52.000Z',
      statusCode: null,
      error: 'ECONNREFUSED 203.0.113.9:443',
    },
  },
]

const attemptsByDelivery: Record<string, DeliveryAttempt[]> = {
  delivery_beijing_0901_c: [
    { id: 'attempt_beijing_0901_c_1', deliveryId: 'delivery_beijing_0901_c', attemptNo: 1, startedAt: '2026-09-01T15:02:01.000Z', finishedAt: '2026-09-01T15:02:44.000Z', statusCode: null, error: 'ECONNREFUSED 203.0.113.9:443' },
    { id: 'attempt_beijing_0901_c_2', deliveryId: 'delivery_beijing_0901_c', attemptNo: 2, startedAt: '2026-09-01T15:14:01.000Z', finishedAt: '2026-09-01T15:14:43.000Z', statusCode: null, error: 'ECONNREFUSED 203.0.113.9:443' },
    { id: 'attempt_beijing_0901_c_3', deliveryId: 'delivery_beijing_0901_c', attemptNo: 3, startedAt: '2026-09-01T15:33:50.000Z', finishedAt: '2026-09-01T15:33:52.000Z', statusCode: null, error: 'ECONNREFUSED 203.0.113.9:443' },
  ],
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

let commandCalls: Array<{ path: string; method: string; body?: unknown; headers?: Record<string, string> }>

function stubApi(options: { invalidSink?: boolean } = {}) {
  commandCalls = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname
    const method = init?.method ?? 'GET'
    const headers = (init?.headers ?? {}) as Record<string, string>
    if (path === `/api/v1/collectors/${collectorId}`) return json(seedCollectors[0])
    if (path === '/api/v1/ai-runs') return json({ items: [], page: { nextCursor: null } })
    if (path.endsWith('/sinks') && method === 'GET') return json({ items: sinks, page: { nextCursor: null } })
    if (path.endsWith('/sinks') && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as SinkInput
      commandCalls.push({ path, method, body, headers })
      if (options.invalidSink) return json({ code: 'INVALID_URL', message: 'invalid webhook url', requestId: 'req_sink_url', retryable: false }, 400)
      const sink: Sink = {
        id: 'sink_created',
        collectorId,
        type: 'webhook',
        url: body.url,
        enabled: body.enabled ?? true,
        version: 1,
        credentialConfigured: Boolean(body.secret?.trim()),
        createdAt: '2026-09-03T01:00:00.000Z',
        updatedAt: '2026-09-03T01:00:00.000Z',
      }
      sinks.push(sink)
      return json(sink, 201)
    }
    if (path.includes('/sinks/') && method === 'PUT') {
      const body = JSON.parse(String(init?.body)) as SinkUpdateInput
      commandCalls.push({ path, method, body, headers })
      const sink = sinks[0]
      if (body.url) sink.url = body.url
      if (body.enabled !== undefined) sink.enabled = body.enabled
      if (body.secret !== undefined) sink.credentialConfigured = body.secret.trim().length > 0
      sink.version += 1
      return json(sink)
    }
    if (path.endsWith('/deliveries')) return json({ items: deliveries, page: { nextCursor: null } })
    if (path.endsWith('/redeliver')) {
      commandCalls.push({ path, method, headers })
      const delivery = deliveries.find((row) => path.includes(row.id))
      if (!delivery) return json({ code: 'DELIVERY_NOT_FOUND', message: 'missing', requestId: 'req_delivery', retryable: false }, 404)
      delivery.status = 'pending'
      delivery.redeliveryCount += 1
      return json(delivery)
    }
    if (path.startsWith('/api/v1/deliveries/')) {
      const id = path.split('/').at(-1) ?? ''
      const delivery = deliveries.find((row) => row.id === id)
      if (!delivery) return json({ code: 'DELIVERY_NOT_FOUND', message: 'missing', requestId: 'req_delivery', retryable: false }, 404)
      const { latestAttempt: _latestAttempt, ...rest } = delivery
      return json({ ...rest, attempts: attemptsByDelivery[id] ?? [] })
    }
    return json({ message: 'not found' }, 404)
  }))
}

function renderCollectorPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/collectors/${collectorId}`]}>
        <Routes>
          <Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}>
            <Route path="/collectors/:collectorId" element={<CollectorPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openConfigurationTab(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText('北京市公共资源交易标讯')
  await user.click(screen.getByRole('tab', { name: '采集配置' }))
  await screen.findByLabelText('Webhook 推送配置')
}

describe('Collector output loop surfaces', () => {
  beforeEach(() => {
    class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    stubApi()
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders webhook sinks and the delivery log inside the configuration tab', async () => {
    const user = userEvent.setup()
    renderCollectorPage()
    await openConfigurationTab(user)

    const webhookPanel = screen.getByLabelText('Webhook 推送配置')
    expect(within(webhookPanel).getByText('https://hooks.example.com/extrio/beijing')).toBeInTheDocument()
    expect(within(webhookPanel).getByText('已启用')).toBeInTheDocument()
    expect(within(webhookPanel).getByText('v1')).toBeInTheDocument()
    expect(within(webhookPanel).getByText('密钥已配置')).toBeInTheDocument()
    expect(within(webhookPanel).getByRole('button', { name: '向 https://hooks.example.com/extrio/beijing 发送测试推送' })).toBeInTheDocument()

    const deliveryPanel = screen.getByLabelText('Webhook 投递记录')
    expect(within(deliveryPanel).getByText('已送达')).toBeInTheDocument()
    expect(within(deliveryPanel).getByText('失败待重试')).toBeInTheDocument()
    expect(within(deliveryPanel).getByText('死信')).toBeInTheDocument()
    expect(within(deliveryPanel).getByText(/502 · upstream connect error/)).toBeInTheDocument()
    expect(within(deliveryPanel).getByRole('button', { name: `重新投递 delivery_beijing_0901_c` })).toBeInTheDocument()
  })

  it('creates a webhook sink with the typed URL and skips empty secrets', async () => {
    const user = userEvent.setup()
    renderCollectorPage()
    await openConfigurationTab(user)

    await user.click(screen.getByRole('button', { name: '添加 Webhook' }))
    await user.type(screen.getByLabelText('Webhook 地址'), 'https://hooks.example.com/extrio/new')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(commandCalls).toHaveLength(1))
    const call = commandCalls[0]
    expect(call.method).toBe('POST')
    expect(call.headers?.['Idempotency-Key']).toBeTruthy()
    expect(call.body).toEqual({ type: 'webhook', url: 'https://hooks.example.com/extrio/new', enabled: true })
    expect(Object.keys(call.body as SinkInput)).not.toContain('secret')
    expect(await screen.findByText('https://hooks.example.com/extrio/new')).toBeInTheDocument()
  })

  it('maps INVALID_URL failures to the scoped webhook hint', async () => {
    stubApi({ invalidSink: true })
    const user = userEvent.setup()
    renderCollectorPage()
    await openConfigurationTab(user)

    await user.click(screen.getByRole('button', { name: '添加 Webhook' }))
    await user.type(screen.getByLabelText('Webhook 地址'), 'https://user:pass@example.com/hook')
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('保存失败：Webhook 地址必须是有效的 HTTP(S) 地址且不能内嵌凭据')).toBeInTheDocument()
  })

  it('keeps the stored secret when editing and only sends the secret when retyped', async () => {
    const user = userEvent.setup()
    renderCollectorPage()
    await openConfigurationTab(user)

    await user.click(screen.getByRole('button', { name: 'https://hooks.example.com/extrio/beijing 的操作' }))
    await user.click(await screen.findByRole('menuitem', { name: '编辑' }))
    expect(screen.getByLabelText('签名密钥')).toHaveAttribute('placeholder', '留空表示保留现有密钥')

    await user.type(screen.getByLabelText('签名密钥'), 'rotated-secret')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(commandCalls).toHaveLength(1))
    expect(commandCalls[0].method).toBe('PUT')
    expect(commandCalls[0].body).toEqual({ url: 'https://hooks.example.com/extrio/beijing', enabled: true, secret: 'rotated-secret' })
  })

  it('redelivers a dead-lettered delivery and refreshes its status', async () => {
    const user = userEvent.setup()
    renderCollectorPage()
    await openConfigurationTab(user)

    await user.click(screen.getByRole('button', { name: `重新投递 delivery_beijing_0901_c` }))

    await waitFor(() => expect(commandCalls.some((call) => call.path.endsWith('/redeliver'))).toBe(true))
    await waitFor(() => {
      const refetches = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/deliveries'))
      expect(refetches.length).toBeGreaterThanOrEqual(2)
    })
    expect(await within(screen.getByLabelText('Webhook 投递记录')).findByText('待投递')).toBeInTheDocument()
  })

  it('expands a delivery row to show the full attempt history', async () => {
    const user = userEvent.setup()
    renderCollectorPage()
    await openConfigurationTab(user)

    await user.click(screen.getByRole('button', { name: '查看投递 delivery_beijing_0901_c 的尝试历史' }))

    expect(await screen.findByText('投递尝试历史')).toBeInTheDocument()
    expect(screen.getByText('第 1 次')).toBeInTheDocument()
    expect(screen.getByText('第 3 次')).toBeInTheDocument()
    expect(screen.getAllByText('ECONNREFUSED 203.0.113.9:443').length).toBeGreaterThan(0)
  })
})
