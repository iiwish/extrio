import { delay, http, HttpResponse } from 'msw'
import { collectionPolicyFor, createCandidateRule, createItemsForCollector, scheduleFor, seedAiRuns, seedCollectors, seedRuns } from './fixtures'
import type {
  AiRunDetail,
  BatchCollectorImportItem,
  CandidateRuleEditInput,
  CollectorDetail,
  CollectorScheduleInput,
  CollectionPolicyInput,
  CreateCollectorInput,
  CreateCollectorsInput,
  Delivery,
  DeliveryAttempt,
  DeliveryStatus,
  DeliverySummary,
  FieldReviewDecision,
  ModelConfiguration,
  ModelConfigurationInput,
  ModelSetting,
  ModelSettingInput,
  Operation,
  PlatformError,
  Run,
  Sink,
  SinkInput,
  SinkUpdateInput,
  UpdateCollectorInput,
  UpdateUserInput,
  User,
  CreateUserInput,
} from './types'

const collectors = structuredClone(seedCollectors)
const runs = structuredClone(seedRuns)
const aiRuns = structuredClone(seedAiRuns)
const sinks: Sink[] = [{
  id: 'sink_beijing_webhook',
  collectorId: 'collector_beijing_tender',
  type: 'webhook',
  url: 'https://hooks.example.com/extrio/beijing',
  enabled: true,
  version: 1,
  credentialConfigured: true,
  createdAt: '2026-08-30T02:00:00.000Z',
  updatedAt: '2026-08-30T02:00:00.000Z',
}]
const deliveryAttempts = new Map<string, DeliveryAttempt[]>()
const deliveries: DeliverySummary[] = seedDeliveries()

function seedDeliveries(): DeliverySummary[] {
  const delivered: DeliverySummary = {
    id: 'delivery_beijing_0902_a',
    collectorId: 'collector_beijing_tender',
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
  }
  const retrying: DeliverySummary = {
    id: 'delivery_beijing_0902_b',
    collectorId: 'collector_beijing_tender',
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
  }
  const deadLettered: DeliverySummary = {
    id: 'delivery_beijing_0901_c',
    collectorId: 'collector_beijing_tender',
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
  }
  deliveryAttempts.set(delivered.id, [
    { id: 'attempt_beijing_0902_a_1', deliveryId: delivered.id, attemptNo: 1, startedAt: '2026-09-02T09:12:02.000Z', finishedAt: '2026-09-02T09:12:30.000Z', statusCode: 500, error: 'upstream timeout' },
    delivered.latestAttempt!,
  ])
  deliveryAttempts.set(retrying.id, [retrying.latestAttempt!])
  deliveryAttempts.set(deadLettered.id, [
    { id: 'attempt_beijing_0901_c_1', deliveryId: deadLettered.id, attemptNo: 1, startedAt: '2026-09-01T15:02:01.000Z', finishedAt: '2026-09-01T15:02:44.000Z', statusCode: null, error: 'ECONNREFUSED 203.0.113.9:443' },
    { id: 'attempt_beijing_0901_c_2', deliveryId: deadLettered.id, attemptNo: 2, startedAt: '2026-09-01T15:14:01.000Z', finishedAt: '2026-09-01T15:14:43.000Z', statusCode: null, error: 'ECONNREFUSED 203.0.113.9:443' },
    deadLettered.latestAttempt!,
  ])
  return [delivered, retrying, deadLettered]
}
const defaultModelSetting: ModelSetting = {
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  model: '',
  secretRef: 'env:EXTRIO_MODEL_API_KEY',
  secretConfigured: false,
  updatedAt: null,
}
const modelSettingStorageKey = 'extrio.mock.model-setting.v1'

function readMockModelSetting(): ModelSetting {
  if (typeof localStorage === 'undefined') return defaultModelSetting
  try {
    return { ...defaultModelSetting, ...JSON.parse(localStorage.getItem(modelSettingStorageKey) ?? '{}') as ModelSetting }
  } catch {
    return defaultModelSetting
  }
}

let modelSetting = readMockModelSetting()

const defaultModelConfiguration: ModelConfiguration = {
  providers: [{
    id: 'provider_openai',
    name: 'OpenAI',
    provider: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    enabled: true,
    credentialConfigured: false,
    updatedAt: null,
  }],
  models: [],
  defaultModelId: null,
  updatedAt: null,
}
const modelConfigurationStorageKey = 'extrio.mock.model-configuration.v2'

function readMockModelConfiguration(): ModelConfiguration {
  if (typeof localStorage === 'undefined') return defaultModelConfiguration
  try {
    const stored = JSON.parse(localStorage.getItem(modelConfigurationStorageKey) ?? '{}') as ModelConfiguration & {
      providers?: Array<ModelConfiguration['providers'][number] & { secretConfigured?: boolean }>
    }
    return {
      ...defaultModelConfiguration,
      ...stored,
      providers: (stored.providers ?? defaultModelConfiguration.providers).map((provider) => {
        const legacyProvider = provider as typeof provider & { secretConfigured?: boolean }
        return {
          id: provider.id,
          name: provider.name,
          provider: provider.provider,
          baseUrl: provider.baseUrl,
          enabled: provider.enabled,
          credentialConfigured: provider.credentialConfigured ?? legacyProvider.secretConfigured ?? false,
          updatedAt: provider.updatedAt,
        }
      }),
    }
  } catch {
    return defaultModelConfiguration
  }
}

let modelConfiguration = readMockModelConfiguration()

interface MockOperation {
  value: Operation
  collectorId: string
  polls: number
  finalized: boolean
}

const operations = new Map<string, MockOperation>()
const mockAuthUser = { id: 'user_mock_admin', username: 'admin', displayName: '林然', role: 'administrator' as const }
const users: User[] = [
  {
    id: mockAuthUser.id,
    username: mockAuthUser.username,
    displayName: mockAuthUser.displayName,
    role: mockAuthUser.role,
    enabled: true,
    createdAt: '2026-08-28T08:00:00.000Z',
    updatedAt: '2026-09-01T09:30:00.000Z',
  },
  {
    id: 'user_mock_engineer',
    username: 'engineer',
    displayName: '陈曦',
    role: 'engineer',
    enabled: true,
    createdAt: '2026-08-29T08:00:00.000Z',
    updatedAt: '2026-08-29T08:00:00.000Z',
  },
  {
    id: 'user_mock_reviewer',
    username: 'reviewer',
    displayName: '沈知言',
    role: 'reviewer',
    enabled: true,
    createdAt: '2026-08-30T08:00:00.000Z',
    updatedAt: '2026-09-02T10:15:00.000Z',
  },
  {
    id: 'user_mock_viewer',
    username: 'viewer',
    displayName: '顾远',
    role: 'viewer',
    enabled: false,
    createdAt: '2026-08-31T08:00:00.000Z',
    updatedAt: '2026-09-02T14:40:00.000Z',
  },
]

const byId = <T extends { id: string }>(rows: T[], id: string) => rows.find((row) => row.id === id)
const requestId = () => `req_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`
const page = <T>(items: T[]) => ({ items, page: { nextCursor: null } })
const emptyMetrics = () => ({
  listPagesFetched: 0,
  detailUrlsDiscovered: 0,
  detailPagesFetched: 0,
  recordsOutsideWindow: 0,
  duplicateDetailUrls: 0,
  newItems: 0,
  updatedItems: 0,
  unchangedItems: 0,
  warningCount: 0,
})

function platformError(code: PlatformError['code'], message: string, requestIdValue = requestId(), retryable = false): PlatformError {
  return { code, message, requestId: requestIdValue, retryable }
}

function successResponse(body: object, status = 200, headers: Record<string, string> = {}) {
  return HttpResponse.json(body, { status, headers: { 'X-Request-ID': requestId(), ...headers } })
}

function errorResponse(code: PlatformError['code'], message: string, status: number) {
  const error = platformError(code, message)
  return HttpResponse.json(error, { status, headers: { 'X-Request-ID': error.requestId } })
}

function requireIdempotency(request: Request) {
  return request.headers.get('Idempotency-Key')?.trim() || null
}

function parseWebhookUrl(value: string): URL | null {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null
    return url
  } catch {
    return null
  }
}

function createMockDelivery(sink: Sink, itemEventId: string): Delivery {
  const now = new Date().toISOString()
  const delivery: Delivery = {
    id: `delivery_${crypto.randomUUID().replaceAll('-', '').slice(0, 20)}`,
    collectorId: sink.collectorId,
    sinkId: sink.id,
    sinkVersionId: `${sink.id}#v${sink.version}`,
    itemEventId,
    status: 'pending',
    attemptCount: 0,
    nextAttemptAt: now,
    leaseUntil: null,
    lastStatusCode: null,
    lastError: null,
    redeliveryCount: 0,
    createdAt: now,
    updatedAt: now,
  }
  if (itemEventId.startsWith('test_')) delivery.kind = 'test'
  return delivery
}

function createOperation(kind: Operation['kind'], collectorId: string, resourceId: string): MockOperation {
  const id = `op_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`
  const operation: MockOperation = {
    value: {
      id,
      kind,
      status: 'queued',
      phase: 'queued',
      progress: 6,
      resourceType: kind === 'run' ? 'run' : 'collector',
      resourceId,
      statusUrl: `/api/v1/operations/${id}`,
      pollAfterMs: 140,
      metrics: emptyMetrics(),
      error: null,
    },
    collectorId,
    polls: 0,
    finalized: false,
  }
  operations.set(id, operation)
  return operation
}

function advanceOperation(operation: MockOperation) {
  if (['succeeded', 'failed', 'cancelled', 'timed_out'].includes(operation.value.status)) return
  operation.polls += 1
  const collector = byId(collectors, operation.collectorId)
  if (!collector) {
    operation.value = {
      ...operation.value,
      status: 'failed',
      phase: 'completed',
      progress: 100,
      error: platformError('COLLECTOR_NOT_FOUND', 'Collector 不存在'),
    }
    return
  }

  const mode = /(?:single|detail-only)/.test(new URL(collector.sourceUrl).pathname) ? 'single' : 'list_detail'
  const phases = operation.value.kind === 'explore'
    ? mode === 'single'
      ? [
          { phase: 'fetching_list' as const, progress: 38, metrics: [1, 0, 0, 0] },
          { phase: 'validating' as const, progress: 82, metrics: [1, 0, 0, 1] },
          { phase: 'completed' as const, progress: 100, metrics: [1, 0, 0, 1] },
        ]
      : [
          { phase: 'fetching_list' as const, progress: 28, metrics: [3, 0, 0, 0] },
          { phase: 'discovering_details' as const, progress: 54, metrics: [3, 12, 0, 0] },
          { phase: 'fetching_details' as const, progress: 76, metrics: [3, 12, 3, 0] },
          { phase: 'validating' as const, progress: 90, metrics: [3, 12, 3, 1] },
          { phase: 'completed' as const, progress: 100, metrics: [3, 12, 3, 1] },
        ]
    : mode === 'single'
      ? [
          { phase: 'fetching_list' as const, progress: 46, metrics: [1, 0, 0, 0] },
          { phase: 'finalizing' as const, progress: 88, metrics: [1, 0, 0, 1] },
          { phase: 'completed' as const, progress: 100, metrics: [1, 0, 0, 1] },
        ]
      : [
          { phase: 'fetching_list' as const, progress: 25, metrics: [4, 0, 0, 0] },
          { phase: 'discovering_details' as const, progress: 48, metrics: [4, 4, 0, 0] },
          { phase: 'fetching_details' as const, progress: 70, metrics: [4, 4, 4, 0] },
          { phase: 'finalizing' as const, progress: 90, metrics: [4, 4, 4, 1] },
          { phase: 'completed' as const, progress: 100, metrics: [4, 4, 4, 1] },
        ]

  const snapshot = phases[Math.min(operation.polls - 1, phases.length - 1)]
  const [listPagesFetched, detailUrlsDiscovered, detailPagesFetched, warningCount] = snapshot.metrics
  operation.value = {
    ...operation.value,
    status: snapshot.phase === 'completed' ? 'succeeded' : 'running',
    phase: snapshot.phase,
    progress: snapshot.progress,
    metrics: { ...emptyMetrics(), listPagesFetched, detailUrlsDiscovered, detailPagesFetched, warningCount },
  }

  if (operation.value.kind === 'explore') {
    const aiRun = aiRuns.find((row) => row.operationId === operation.value.id)
    if (aiRun && snapshot.phase !== 'completed') {
      aiRun.status = 'running'
      aiRun.phase = snapshot.phase
      aiRun.progress = snapshot.progress
      aiRun.startedAt ??= new Date().toISOString()
      aiRun.attemptCount = 1
    }
  }

  if (operation.value.kind === 'run' && snapshot.phase !== 'completed') {
    const activeRun = byId(runs, operation.value.resourceId)
    if (activeRun) activeRun.status = snapshot.phase === 'finalizing' ? 'finalizing' : 'running'
  }

  if (snapshot.phase !== 'completed' || operation.finalized) return
  operation.finalized = true
  if (operation.value.kind === 'explore') {
    const aiRun = aiRuns.find((row) => row.operationId === operation.value.id)
    if (aiRun) {
      aiRun.status = 'succeeded'
      aiRun.phase = 'completed'
      aiRun.progress = 100
      aiRun.resultStatus = 'candidate_ready'
      aiRun.reviewStatus = 'ready_review'
      aiRun.finishedAt = new Date().toISOString()
      aiRun.durationMs = 24000
      aiRun.validationSummary = { acceptedSamples: 3, rejectedSamples: 0, warningCount: 0 }
      aiRun.candidateRuleDigest = createCandidateRule(collector).digest
    }
    collector.status = 'ready_review'
    collector.activeOperationId = null
    collector.candidate = createCandidateRule(collector)
    collector.previewItems = createItemsForCollector(collector, `run_preview_${collector.id}`, 'candidate')
    collector.updatedAt = '刚刚'
    return
  }

  const run = byId(runs, operation.value.resourceId)
  if (!run) return
  const items = createItemsForCollector(collector, run.id, run.ruleVersion)
  run.status = 'partially_succeeded'
  run.duration = '1m 12s'
  run.acceptedCount = 3
  run.rejectedCount = 1
  run.pagesFetched = mode === 'single' ? 1 : 8
  run.listPagesFetched = mode === 'single' ? 1 : 4
  run.detailUrlsDiscovered = mode === 'single' ? 0 : 4
  run.detailPagesFetched = mode === 'single' ? 0 : 4
  run.recordsOutsideWindow = mode === 'single' ? 0 : 12
  run.duplicateDetailUrls = 0
  run.newItems = 2
  run.updatedItems = 1
  run.unchangedItems = 0
  run.paginationStopReason = mode === 'single' ? 'not_applicable' : 'empty_page'
  run.summary = '1 个候选因必填字段 buyer 为空被拒绝；3 个 accepted Item 已冻结。'
  run.recoveryAction = '检查拒绝候选的 Source 结构；如结构已漂移，重新探索并发布新规则。'
  run.items = items
  collector.latestRunId = run.id
  collector.previewItems = items
  collector.updatedAt = '刚刚'
}

// Minimal deterministic stored-entry ZIP (single manifest member) so the mock contract
// environment hands back a genuinely openable archive; the real bundle is signed server-side.
const ZIP_CRC_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index
  for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
  return value >>> 0
})

function zipCrc32(content: Uint8Array): number {
  let crc = 0xffffffff
  for (const byte of content) crc = ZIP_CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

function mockEvidenceBundleZip(collectorId: string): Uint8Array {
  const encoder = new TextEncoder()
  const name = encoder.encode('manifest.json')
  const content = encoder.encode(JSON.stringify({ bundleVersion: 'extrio.evidence.v1', collector: { id: collectorId } }, null, 2))
  const crc = zipCrc32(content)
  const record = (view: DataView) => {
    view.setUint16(0, 20, true)
    view.setUint16(8, 0, true)
    view.setUint32(14, crc, true)
    view.setUint32(18, content.length, true)
    view.setUint32(22, content.length, true)
    view.setUint16(26, name.length, true)
  }
  const local = new Uint8Array(30 + name.length + content.length)
  record(new DataView(local.buffer))
  local.set([0x50, 0x4b, 0x03, 0x04], 0)
  local.set(name, 30)
  local.set(content, 30 + name.length)
  const centralOffset = local.length
  const central = new Uint8Array(46 + name.length)
  record(new DataView(central.buffer))
  central.set([0x50, 0x4b, 0x01, 0x02], 0)
  central.set(name, 46)
  const end = new Uint8Array(22)
  const endView = new DataView(end.buffer)
  end.set([0x50, 0x4b, 0x05, 0x06], 0)
  endView.setUint16(8, 1, true)
  endView.setUint16(10, 1, true)
  endView.setUint32(12, central.length, true)
  endView.setUint32(16, centralOffset, true)
  const archive = new Uint8Array(local.length + central.length + end.length)
  archive.set(local, 0)
  archive.set(central, local.length)
  archive.set(end, local.length + central.length)
  return archive
}

export const handlers = [
  http.get('*/api/v1/auth/state', () => successResponse({
    authEnabled: true,
    setupRequired: false,
    authenticated: true,
    user: mockAuthUser,
  })),
  http.post('*/api/v1/auth/setup', () => successResponse({
    authEnabled: true,
    setupRequired: false,
    authenticated: true,
    user: mockAuthUser,
  })),
  http.post('*/api/v1/auth/login', () => successResponse({
    authEnabled: true,
    setupRequired: false,
    authenticated: true,
    user: mockAuthUser,
  })),
  http.post('*/api/v1/auth/logout', () => successResponse({ authenticated: false })),
  http.get('*/api/v1/users', () => successResponse(page(users))),
  http.post('*/api/v1/users', async ({ request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    await delay(120)
    const input = await request.json() as CreateUserInput
    if (!/^[A-Za-z0-9_.-]{3,64}$/.test(input.username)) {
      return errorResponse('VALIDATION_FAILED', '用户名必须为 3-64 位字母、数字或 ._-', 422)
    }
    if (!input.password || input.password.length < 8) {
      return errorResponse('VALIDATION_FAILED', '密码长度至少为 8 个字符', 422)
    }
    if (!['administrator', 'engineer', 'reviewer', 'viewer'].includes(input.role)) {
      return errorResponse('VALIDATION_FAILED', '角色无效', 422)
    }
    if (users.some((user) => user.username.toLowerCase() === input.username.toLowerCase())) {
      return errorResponse('USERNAME_TAKEN', '用户名已存在', 409)
    }
    const now = new Date().toISOString()
    const user: User = {
      id: `user_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`,
      username: input.username,
      displayName: input.displayName?.trim() || input.username,
      role: input.role,
      enabled: true,
      createdAt: now,
      updatedAt: now,
    }
    users.push(user)
    return successResponse(user, 201, { Location: `/api/v1/users/${user.id}` })
  }),
  http.patch('*/api/v1/users/:userId', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const user = byId(users, String(params.userId))
    if (!user) return errorResponse('USER_NOT_FOUND', '用户不存在', 404)
    const input = await request.json() as UpdateUserInput
    if (input.role !== undefined && !['administrator', 'engineer', 'reviewer', 'viewer'].includes(input.role)) {
      return errorResponse('VALIDATION_FAILED', '角色无效', 422)
    }
    if (input.enabled !== undefined && typeof input.enabled !== 'boolean') {
      return errorResponse('VALIDATION_FAILED', 'enabled 必须是布尔值', 422)
    }
    if (user.id === mockAuthUser.id && input.enabled === false) {
      return errorResponse('SELF_DISABLE', '不能禁用当前登录的账号', 409)
    }
    const demotesLastAdministrator = user.role === 'administrator' && user.enabled
      && ((input.role !== undefined && input.role !== 'administrator') || input.enabled === false)
      && users.filter((row) => row.role === 'administrator' && row.enabled).length <= 1
    if (demotesLastAdministrator) {
      return errorResponse('LAST_ADMINISTRATOR', '不能移除最后一个可用的管理员账号', 409)
    }
    if (input.role !== undefined) user.role = input.role
    if (input.displayName !== undefined) user.displayName = input.displayName
    if (input.enabled !== undefined) user.enabled = input.enabled
    user.updatedAt = new Date().toISOString()
    return successResponse(user)
  }),
  http.get('*/api/v1/settings/models', () => successResponse(modelConfiguration)),
  http.put('*/api/v1/settings/models', async ({ request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const input = await request.json() as ModelConfigurationInput
    const invalidProvider = input.providers.find((provider) => (
      !['openai', 'deepseek', 'qwen', 'custom'].includes(provider.provider)
      || !provider.baseUrl.startsWith('https://')
    ))
    if (invalidProvider) return errorResponse('VALIDATION_FAILED', '供应商配置无效', 422)
    const providerIds = new Set(input.providers.map((provider) => provider.id))
    if (input.models.some((model) => !providerIds.has(model.providerId) || !model.modelId.trim())) {
      return errorResponse('VALIDATION_FAILED', '模型配置无效', 422)
    }
    const enabledProviderIds = new Set(input.providers.filter((provider) => provider.enabled).map((provider) => provider.id))
    const enabledModelIds = new Set(input.models.filter((model) => model.enabled && enabledProviderIds.has(model.providerId)).map((model) => model.id))
    if (input.defaultModelId && !enabledModelIds.has(input.defaultModelId)) {
      return errorResponse('VALIDATION_FAILED', '默认模型必须可用', 422)
    }
    const updatedAt = new Date().toISOString()
    modelConfiguration = {
      providers: input.providers.map((provider) => {
        const previous = modelConfiguration.providers.find((row) => row.id === provider.id)
        return {
          id: provider.id,
          name: provider.name,
          provider: provider.provider,
          baseUrl: provider.baseUrl,
          enabled: provider.enabled,
          credentialConfigured: Boolean(provider.apiKey?.trim()) || previous?.credentialConfigured === true,
          updatedAt,
        }
      }),
      models: input.models.map((model) => ({ ...model, isDefault: model.id === input.defaultModelId, updatedAt })),
      defaultModelId: input.defaultModelId,
      updatedAt,
    }
    if (typeof localStorage !== 'undefined') localStorage.setItem(modelConfigurationStorageKey, JSON.stringify(modelConfiguration))
    return successResponse(modelConfiguration)
  }),
  http.get('*/api/v1/settings/model', () => successResponse(modelSetting)),
  http.put('*/api/v1/settings/model', async ({ request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const input = await request.json() as ModelSettingInput
    if (!['openai', 'deepseek', 'qwen', 'custom'].includes(input.provider)) {
      return errorResponse('VALIDATION_FAILED', '不支持的模型供应商', 422)
    }
    if (!input.baseUrl.startsWith('https://')) return errorResponse('VALIDATION_FAILED', '模型 API 地址必须是有效的 HTTPS URL', 422)
    if (!input.model.trim()) return errorResponse('VALIDATION_FAILED', '模型 ID 不能为空', 422)
    if (!/^env:[A-Z][A-Z0-9_]{2,127}$/.test(input.secretRef)) {
      return errorResponse('VALIDATION_FAILED', '密钥引用必须使用 env:VARIABLE_NAME 格式', 422)
    }
    modelSetting = { ...input, secretConfigured: false, updatedAt: new Date().toISOString() }
    if (typeof localStorage !== 'undefined') localStorage.setItem(modelSettingStorageKey, JSON.stringify(modelSetting))
    return successResponse(modelSetting)
  }),
  http.get('*/api/v1/collectors', () => successResponse(page(collectors))),
  http.get('*/api/v1/collectors/:id', ({ params }) => {
    const collector = byId(collectors, String(params.id))
    return collector ? successResponse(collector) : errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
  }),
  http.patch('*/api/v1/collectors/:id', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    const input = await request.json() as UpdateCollectorInput
    let sourceUrl: URL
    try {
      sourceUrl = new URL(input.sourceUrl)
    } catch {
      return errorResponse('INVALID_URL', 'URL 格式无效', 422)
    }
    if (!['http:', 'https:'].includes(sourceUrl.protocol)) return errorResponse('INVALID_URL', 'Source 仅支持 HTTP 或 HTTPS', 422)
    if (collectors.some((row) => row.id !== collector.id && row.sourceUrl === sourceUrl.toString())) {
      return errorResponse('SOURCE_ALREADY_EXISTS', '该 Source URL 已存在', 409)
    }
    const ruleInputChanged = collector.intent !== input.intent.trim() || collector.sourceUrl !== sourceUrl.toString()
    collector.name = input.name.trim()
    collector.intent = input.intent.trim()
    collector.sourceUrl = sourceUrl.toString()
    collector.sourceHost = sourceUrl.host
    collector.updatedAt = '刚刚'
    if (ruleInputChanged) {
      collector.status = 'draft'
      collector.candidate = null
      collector.previewItems = []
      collector.reviewDecisions = null
    }
    return successResponse(collector)
  }),
  http.post('*/api/v1/collectors', async ({ request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    await delay(120)
    const input = (await request.json()) as CreateCollectorInput
    let url: URL
    try {
      url = new URL(input.sourceUrl)
    } catch {
      return errorResponse('INVALID_URL', 'URL 格式无效', 422)
    }
    const collectorId = `collector_${Date.now()}`
    const collector: CollectorDetail = {
      ...input,
      id: collectorId,
      sourceHost: url.host,
      sourceUrl: url.toString(),
      status: 'draft',
      collectionId: `collection_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`,
      collectionName: input.name,
      collectionVersion: 'tender_notice_v4',
      activeRuleVersion: null,
      activeCollectionPolicyId: collectionPolicyFor(collectorId).id,
      activeOperationId: null,
      latestRunId: null,
      updatedAt: '刚刚',
      candidate: null,
      previewItems: [],
      reviewDecisions: null,
      collectionPolicy: null,
      checkpoint: null,
      schedule: scheduleFor(collectorId),
    }
    collector.collectionPolicy = collectionPolicyFor(collector.id)
    collector.activeCollectionPolicyId = collector.collectionPolicy.id
    collectors.unshift(collector)
    return successResponse(collector, 201, { Location: `/api/v1/collectors/${collector.id}` })
  }),
  http.post('*/api/v1/collectors/batch', async ({ request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    await delay(180)
    const input = (await request.json()) as CreateCollectorsInput
    const existingCollection = input.collectionId
      ? collectors.find((collector) => collector.collectionId === input.collectionId)
      : undefined
    if (input.collectionId && !existingCollection) return errorResponse('COLLECTION_NOT_FOUND', '采集需求不存在', 404)
    const collectionId = existingCollection?.collectionId ?? `collection_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`
    const collectionName = existingCollection?.collectionName ?? input.collectionName
    const collectionVersion = existingCollection?.collectionVersion ?? 'tender_notice_v4'
    const intent = existingCollection?.intent ?? input.intent
    const seen = new Set<string>()
    const results: BatchCollectorImportItem[] = input.sourceUrls.map((rawUrl, index) => {
      const sourceUrl = rawUrl.trim()
      let url: URL
      try {
        url = new URL(sourceUrl)
      } catch {
        return { sourceUrl, status: 'rejected', collector: null, error: platformError('INVALID_URL', 'URL 格式无效') }
      }
      if (!['http:', 'https:'].includes(url.protocol)) {
        return { sourceUrl, status: 'rejected', collector: null, error: platformError('INVALID_URL', 'Source 仅支持 HTTP 或 HTTPS') }
      }
      const canonicalUrl = url.toString()
      if (seen.has(canonicalUrl)) {
        return { sourceUrl, status: 'rejected', collector: null, error: platformError('DUPLICATE_IN_BATCH', '批次内 URL 重复') }
      }
      seen.add(canonicalUrl)
      if (collectors.some((collector) => collector.sourceUrl === canonicalUrl)) {
        return { sourceUrl, status: 'rejected', collector: null, error: platformError('SOURCE_ALREADY_EXISTS', '该 Source URL 已存在') }
      }
      const collectorId = `collector_${url.host.replace(/[^a-z0-9]+/gi, '_')}_${Date.now()}_${index}`
      const collector: CollectorDetail = {
        id: collectorId,
        name: url.host,
        intent,
        sourceUrl: canonicalUrl,
        sourceHost: url.host,
        status: 'draft',
        collectionId,
        collectionName,
        collectionVersion,
        activeRuleVersion: null,
        activeCollectionPolicyId: null,
        activeOperationId: null,
        latestRunId: null,
        updatedAt: '刚刚',
        candidate: null,
        previewItems: [],
        reviewDecisions: null,
        collectionPolicy: null,
        checkpoint: null,
        schedule: scheduleFor(collectorId),
      }
      collector.collectionPolicy = collectionPolicyFor(collector.id)
      collector.activeCollectionPolicyId = collector.collectionPolicy.id
      collectors.unshift(collector)
      return { sourceUrl, status: 'created', collector, error: null }
    })
    const createdCount = results.filter((result) => result.status === 'created').length
    return successResponse({
      collectionId,
      collectionName,
      collectionVersion,
      total: results.length,
      createdCount,
      rejectedCount: results.length - createdCount,
      results,
    })
  }),
  http.post('*/api/v1/collectors/:id/explorations', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    if (collector.activeOperationId) {
      const active = operations.get(collector.activeOperationId)
      if (active && !['succeeded', 'failed', 'cancelled', 'timed_out'].includes(active.value.status)) {
        return errorResponse('OPERATION_ALREADY_ACTIVE', 'Collector 已有进行中的探索任务', 409)
      }
    }
    collector.status = 'exploring'
    const operation = createOperation('explore', collector.id, collector.id)
    const aiRunId = `ai_run_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`
    const aiRun: AiRunDetail = {
      id: aiRunId,
      operationId: operation.value.id,
      collectorId: collector.id,
      collectorName: collector.name,
      sourceUrl: collector.sourceUrl,
      kind: collector.activeRuleVersion || collector.candidate ? 'rule_repair' : 'rule_generation',
      trigger: collector.activeRuleVersion || collector.candidate ? 'regeneration' : 'initial_generation',
      initiatedBy: mockAuthUser.id,
      status: 'queued',
      phase: 'queued',
      progress: 0,
      resultStatus: 'pending',
      reviewStatus: 'not_ready',
      attemptCount: 0,
      modelSummary: { invocationCount: 0, promptTokens: 0, completionTokens: 0, totalTokens: 0, estimatedCost: null },
      validationSummary: { acceptedSamples: 0, rejectedSamples: 0, warningCount: 0 },
      candidateRuleDigest: null,
      publishedRuleVersionId: null,
      createdAt: new Date().toISOString(),
      startedAt: null,
      finishedAt: null,
      durationMs: null,
      error: null,
      attempts: [],
    }
    aiRuns.unshift(aiRun)
    collector.activeOperationId = operation.value.id
    return successResponse(operation.value, 202, { Location: operation.value.statusUrl })
  }),
  http.post('*/api/v1/collectors/:id/repairs', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    if (!collector.candidate?.gatherSpec && !collector.activeRuleVersion) {
      return errorResponse('REPAIR_NOT_APPLICABLE', 'Collector 尚无可修复的规则，请先完成探索并发布或生成候选规则', 409)
    }
    if (collector.activeOperationId) {
      const active = operations.get(collector.activeOperationId)
      if (active && !['succeeded', 'failed', 'cancelled', 'timed_out'].includes(active.value.status)) {
        return errorResponse('OPERATION_ALREADY_ACTIVE', 'Collector 已有进行中的异步任务', 409)
      }
    }
    const note = (await request.json().catch(() => null) as { note?: string } | null)?.note?.trim()
    collector.status = 'exploring'
    const operation = createOperation('explore', collector.id, collector.id)
    const aiRunId = `ai_run_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`
    const aiRun: AiRunDetail = {
      id: aiRunId,
      operationId: operation.value.id,
      collectorId: collector.id,
      collectorName: collector.name,
      sourceUrl: collector.sourceUrl,
      kind: 'rule_repair',
      trigger: 'repair',
      initiatedBy: mockAuthUser.id,
      status: 'queued',
      phase: 'queued',
      progress: 0,
      resultStatus: 'pending',
      reviewStatus: 'not_ready',
      attemptCount: 0,
      modelSummary: { invocationCount: 0, promptTokens: 0, completionTokens: 0, totalTokens: 0, estimatedCost: null },
      validationSummary: { acceptedSamples: 0, rejectedSamples: 0, warningCount: 0 },
      candidateRuleDigest: null,
      publishedRuleVersionId: null,
      createdAt: new Date().toISOString(),
      startedAt: null,
      finishedAt: null,
      durationMs: null,
      error: null,
      attempts: [],
    }
    if (note) aiRun.note = note
    aiRuns.unshift(aiRun)
    collector.activeOperationId = operation.value.id
    return successResponse(operation.value, 202, { Location: operation.value.statusUrl })
  }),
  http.get('*/api/v1/collectors/:id/evidence-bundle', ({ params }) => {
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    return new HttpResponse(mockEvidenceBundleZip(collector.id), {
      status: 200,
      headers: {
        'X-Request-ID': requestId(),
        'Content-Type': 'application/zip',
        'Content-Disposition': `attachment; filename="extrio-evidence-${collector.id}.zip"`,
      },
    })
  }),
  http.get('*/api/v1/operations/:id', ({ params }) => {
    const operation = operations.get(String(params.id))
    if (!operation) return errorResponse('OPERATION_NOT_FOUND', 'Operation 不存在', 404)
    advanceOperation(operation)
    return successResponse(operation.value, 200, { 'Retry-After': '0' })
  }),
  http.post('*/api/v1/collectors/:id/collection-policy', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    const input = await request.json() as CollectionPolicyInput
    const version = (collector.collectionPolicy?.version ?? 0) + 1
    collector.collectionPolicy = { ...collectionPolicyFor(collector.id, version), ...input }
    collector.activeCollectionPolicyId = collector.collectionPolicy.id
    collector.checkpoint = null
    collector.updatedAt = '刚刚'
    return successResponse(collector)
  }),
  http.put('*/api/v1/collectors/:id/schedule', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    const input = await request.json() as CollectorScheduleInput
    const revision = collector.schedule.revision + 1
    collector.schedule = {
      ...collector.schedule,
      ...input,
      revision,
      lastTriggeredAt: collector.schedule.lastTriggeredAt,
      nextRunAt: input.enabled ? new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString() : null,
      updatedAt: new Date().toISOString(),
    }
    collector.updatedAt = '刚刚'
    return successResponse(collector)
  }),
  http.patch('*/api/v1/collectors/:id/candidate-rule', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    if (!collector.candidate) return errorResponse('CANDIDATE_RULE_NOT_FOUND', '请先探索并生成候选规则', 409)
    const input = await request.json() as CandidateRuleEditInput
    const candidate = structuredClone(collector.candidate)
    candidate.id = `candidate_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`
    candidate.digest = `sha256:${crypto.randomUUID().replaceAll('-', '').padEnd(64, '0')}`
    candidate.listSelector = input.listSelector
    candidate.detailLinkSelector = input.detailLinkSelector
    candidate.pagination = input.pagination
    candidate.gatherSpec.collect.list.itemsSelector = input.listSelector
    candidate.gatherSpec.collect.list.pagination = input.pagination.type === 'page'
      ? { ...input.pagination, location: 'query' }
      : input.pagination
    candidate.gatherSpec.collect.budget.maxPages = 'maxPages' in input.pagination ? input.pagination.maxPages : 1
    if (candidate.mode === 'list_detail' && candidate.gatherSpec.collect.detail && input.detailLinkSelector) {
      input.listFields?.forEach(({ key, selector }) => {
        if (candidate.gatherSpec.collect.list.fields[key]) candidate.gatherSpec.collect.list.fields[key].selector = selector
      })
      candidate.gatherSpec.collect.list.fields.detailUrl.selector = input.detailLinkSelector
      input.fields.forEach(({ key, selector }) => {
        if (candidate.gatherSpec.collect.detail?.fields[key]) candidate.gatherSpec.collect.detail.fields[key].selector = selector
      })
    } else {
      input.fields.forEach(({ key, selector }) => {
        if (candidate.gatherSpec.collect.list.fields[key]) candidate.gatherSpec.collect.list.fields[key].selector = selector
      })
    }
    candidate.fields.forEach((field) => {
      const edited = input.fields.find((row) => row.key === field.key)
      if (edited) field.selector = edited.selector
    })
    collector.candidate = candidate
    collector.status = 'ready_review'
    collector.reviewDecisions = null
    collector.updatedAt = '刚刚'
    return successResponse(collector)
  }),
  http.post('*/api/v1/collectors/:id/publish', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    await delay(180)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    const body = await request.json().catch(() => null) as { reviewDecisions?: Record<string, FieldReviewDecision> } | null
    const reviewDecisions = body?.reviewDecisions
    const allowedDecisions: FieldReviewDecision[] = ['approved', 'risk_accepted', 'excluded']
    const fields = collector.candidate?.fields ?? []
    const invalidDecision = (field: (typeof fields)[number]) => {
      const decision = reviewDecisions?.[field.key]
      if (!decision || !allowedDecisions.includes(decision)) return true
      if (field.required) return decision !== 'approved'
      if (field.warning) return !['risk_accepted', 'excluded'].includes(decision)
      return !['approved', 'excluded'].includes(decision)
    }
    if (!reviewDecisions || fields.length === 0 || fields.some(invalidDecision)) {
      return errorResponse('REVIEW_DECISION_INVALID', '每个候选字段都必须具有有效的审核决定', 409)
    }
    collector.status = 'published'
    const currentVersion = Number(collector.activeRuleVersion?.match(/\d+$/)?.[0] ?? 0)
    collector.activeRuleVersion = `rule_v${currentVersion + 1}`
    collector.reviewDecisions = reviewDecisions
    collector.updatedAt = '刚刚'
    const latestAiRun = aiRuns.find((run) => run.collectorId === collector.id && run.reviewStatus === 'ready_review')
    if (latestAiRun) {
      latestAiRun.reviewStatus = 'published'
      latestAiRun.publishedRuleVersionId = collector.activeRuleVersion
    }
    return successResponse(collector)
  }),
  http.post('*/api/v1/collectors/:id/runs', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    if (collector.status !== 'published' || !collector.activeRuleVersion) return errorResponse('RULE_NOT_PUBLISHED', 'Collector 没有可执行的已发布规则', 409)
    if (runs.some((row) => row.collectorId === collector.id && ['queued', 'running', 'finalizing'].includes(row.status))) {
      return errorResponse('RUN_ALREADY_ACTIVE', 'Collector 已有进行中的 Run', 409)
    }
    const id = `run_${String(Date.now()).slice(-6)}`
    const operation = createOperation('run', collector.id, id)
    const run: Run = {
      id,
      operationId: operation.value.id,
      collectorId: collector.id,
      collectorName: collector.name,
      collectionMode: collector.candidate?.mode ?? (/\/(?:single|detail-only)(?:\/|$)/.test(new URL(collector.sourceUrl).pathname) ? 'single' : 'list_detail'),
      status: 'queued',
      startedAt: '刚刚',
      startedAtIso: new Date().toISOString(),
      duration: '—',
      acceptedCount: 0,
      rejectedCount: 0,
      pagesFetched: 0,
      listPagesFetched: 0,
      detailUrlsDiscovered: 0,
      detailPagesFetched: 0,
      recordsOutsideWindow: 0,
      duplicateDetailUrls: 0,
      newItems: 0,
      updatedItems: 0,
      unchangedItems: 0,
      paginationStopReason: 'not_applicable',
      ruleVersion: collector.activeRuleVersion,
      ruleDigest: collector.candidate?.gatherSpec.integrity.ruleDigest ?? `sha256:${'0'.repeat(64)}`,
      ruleAttestationId: `attestation_${collector.activeRuleVersion}`,
      signingKeyId: 'signingkey_local_dev_v1',
      trustRevision: 1,
      integrityStatus: 'verified',
      policyContextStatus: 'fixed',
      policyVersion: collector.collectionPolicy?.id ?? 'policy_unavailable',
      policyDigest: collector.collectionPolicy?.digest ?? `sha256:${'0'.repeat(64)}`,
      executionMode: collector.checkpoint ? 'incremental' : 'initial',
      windowStart: collector.checkpoint?.watermark ?? '2026-08-01',
      checkpointBefore: collector.checkpoint,
      checkpointAfter: null,
      artifactMode: 'sampled',
      summary: '等待执行 Worker。',
      recoveryAction: '无需操作。',
      items: [],
    }
    runs.unshift(run)
    return successResponse(operation.value, 202, { Location: operation.value.statusUrl })
  }),
  http.get('*/api/v1/runs', () => successResponse(page(runs))),
  http.get('*/api/v1/runs/:id', ({ params }) => {
    const run = byId(runs, String(params.id))
    return run ? successResponse(run) : errorResponse('RUN_NOT_FOUND', 'Run 不存在', 404)
  }),
  http.get('*/api/v1/ai-runs', ({ request }) => {
    const collectorId = new URL(request.url).searchParams.get('collectorId')
    const matches = collectorId ? aiRuns.filter((run) => run.collectorId === collectorId) : aiRuns
    return successResponse(page(matches.map(({ attempts: _attempts, ...run }) => run)))
  }),
  http.get('*/api/v1/ai-runs/:id', ({ params }) => {
    const aiRun = byId(aiRuns, String(params.id))
    return aiRun ? successResponse(aiRun) : errorResponse('AI_RUN_NOT_FOUND', 'AI 任务不存在', 404)
  }),
  http.get('*/api/v1/items/export', ({ request }) => {
    const url = new URL(request.url)
    const format = url.searchParams.get('format')
    if (format !== 'csv' && format !== 'jsonl') {
      return errorResponse('VALIDATION_FAILED', 'format 必须是 csv 或 jsonl', 422)
    }
    const collectorId = url.searchParams.get('collectorId')
    const decision = url.searchParams.get('decision')
    const entityKey = url.searchParams.get('entityKey')
    const items = runs.flatMap((run) => run.items).filter((item) =>
      (!collectorId || item.collectorId === collectorId)
      && (!decision || item.decision === decision)
      && (!entityKey || item.entityKey === entityKey))
    const headers: Record<string, string> = {
      'X-Request-ID': requestId(),
      'Content-Disposition': `attachment; filename="extrio-items.${format}"`,
    }
    if (format === 'jsonl') {
      return new HttpResponse(items.map((item) => JSON.stringify(item)).join('\n'), {
        status: 200,
        headers: { ...headers, 'Content-Type': 'application/x-ndjson' },
      })
    }
    const columns = ['entityKey', 'revision', 'decision', 'changeType', 'collectorName', 'sourceHost', 'sourceUrl', 'publishedAt', 'observedAt']
    const extractedColumns = [...new Set(items.flatMap((item) => Object.keys(item.extractedData ?? {})))].sort()
    const escape = (value: unknown) => {
      if (value === null || value === undefined) return ''
      const text = typeof value === 'string' ? value : String(JSON.stringify(value))
      return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
    }
    const lines = [
      [...columns, ...extractedColumns].join(','),
      ...items.map((item) => [
        ...columns.map((column) => escape(item[column as keyof typeof item])),
        ...extractedColumns.map((column) => escape((item.extractedData as Record<string, unknown> | undefined)?.[column])),
      ].join(',')),
    ]
    return new HttpResponse(`\ufeff${lines.join('\r\n')}`, {
      status: 200,
      headers: { ...headers, 'Content-Type': 'text/csv; charset=utf-8' },
    })
  }),
  http.get('*/api/v1/items', ({ request }) => {
    const url = new URL(request.url)
    const limit = Number.parseInt(url.searchParams.get('limit') ?? '50', 10) || 50
    const all = runs.flatMap((run) => run.items)
    const cursor = url.searchParams.get('cursor')
    let start = 0
    if (cursor) {
      const decoded = Number.parseInt(atob(cursor), 10)
      if (!Number.isInteger(decoded) || decoded < 0) {
        return errorResponse('INVALID_CURSOR', 'Cursor 无效，请使用上一页响应返回的 nextCursor', 400)
      }
      start = decoded
    }
    const items = all.slice(start, start + limit)
    const nextCursor = start + limit < all.length ? btoa(String(start + limit)) : null
    return successResponse({ items, page: { nextCursor }, nextCursor })
  }),
  http.get('*/api/v1/items/:id', ({ params }) => {
    const item = runs.flatMap((run) => run.items).find((row) => row.id === String(params.id))
    return item ? successResponse(item) : errorResponse('ITEM_NOT_FOUND', 'Item 或拒绝候选不存在', 404)
  }),
  http.get('*/api/v1/collectors/:id/sinks', ({ params }) => {
    if (!byId(collectors, String(params.id))) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    return successResponse(page(sinks.filter((sink) => sink.collectorId === String(params.id))))
  }),
  http.post('*/api/v1/collectors/:id/sinks', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const collector = byId(collectors, String(params.id))
    if (!collector) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    const input = await request.json() as SinkInput
    if (input.type !== undefined && input.type !== 'webhook') {
      return errorResponse('VALIDATION_FAILED', '当前仅支持 webhook Sink', 422)
    }
    const url = parseWebhookUrl(input.url)
    if (!url) return errorResponse('INVALID_URL', 'Sink URL 仅支持 HTTP 或 HTTPS 且不能嵌入凭据', 400)
    const now = new Date().toISOString()
    const sink: Sink = {
      id: `sink_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`,
      collectorId: collector.id,
      type: 'webhook',
      url: url.toString(),
      enabled: input.enabled ?? true,
      version: 1,
      credentialConfigured: Boolean(input.secret?.trim()),
      createdAt: now,
      updatedAt: now,
    }
    sinks.unshift(sink)
    return successResponse(sink, 201)
  }),
  http.put('*/api/v1/collectors/:id/sinks/:sinkId', async ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const sink = sinks.find((row) => row.id === String(params.sinkId) && row.collectorId === String(params.id))
    if (!sink) return errorResponse('SINK_NOT_FOUND', 'Sink 不存在', 404)
    const input = await request.json() as SinkUpdateInput
    if (input.url !== undefined) {
      const url = parseWebhookUrl(input.url)
      if (!url) return errorResponse('INVALID_URL', 'Sink URL 仅支持 HTTP 或 HTTPS 且不能嵌入凭据', 400)
      sink.url = url.toString()
    }
    if (input.enabled !== undefined) sink.enabled = input.enabled
    if (input.secret !== undefined) sink.credentialConfigured = input.secret.trim().length > 0
    sink.version += 1
    sink.updatedAt = new Date().toISOString()
    return successResponse(sink)
  }),
  http.delete('*/api/v1/collectors/:id/sinks/:sinkId', ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const index = sinks.findIndex((row) => row.id === String(params.sinkId) && row.collectorId === String(params.id))
    if (index === -1) return errorResponse('SINK_NOT_FOUND', 'Sink 不存在', 404)
    sinks.splice(index, 1)
    return new HttpResponse(null, { status: 204, headers: { 'X-Request-ID': requestId() } })
  }),
  http.post('*/api/v1/collectors/:id/sinks/:sinkId/test', ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const sink = sinks.find((row) => row.id === String(params.sinkId) && row.collectorId === String(params.id))
    if (!sink) return errorResponse('SINK_NOT_FOUND', 'Sink 不存在', 404)
    const delivery = createMockDelivery(sink, `test_${crypto.randomUUID().replaceAll('-', '')}`)
    deliveries.unshift({ ...delivery, latestAttempt: null })
    return successResponse(delivery, 202, { Location: `/api/v1/deliveries/${delivery.id}` })
  }),
  http.get('*/api/v1/collectors/:id/deliveries', ({ params }) => {
    if (!byId(collectors, String(params.id))) return errorResponse('COLLECTOR_NOT_FOUND', 'Collector 不存在', 404)
    return successResponse(page(deliveries.filter((row) => row.collectorId === String(params.id))))
  }),
  http.get('*/api/v1/deliveries/:id', ({ params }) => {
    const delivery = deliveries.find((row) => row.id === String(params.id))
    if (!delivery) return errorResponse('DELIVERY_NOT_FOUND', 'Delivery 不存在', 404)
    const { latestAttempt: _latestAttempt, ...rest } = delivery
    return successResponse({ ...rest, attempts: deliveryAttempts.get(delivery.id) ?? [] })
  }),
  http.post('*/api/v1/deliveries/:id/redeliver', ({ params, request }) => {
    if (!requireIdempotency(request)) return errorResponse('IDEMPOTENCY_KEY_REQUIRED', '缺少 Idempotency-Key', 400)
    const delivery = deliveries.find((row) => row.id === String(params.id))
    if (!delivery) return errorResponse('DELIVERY_NOT_FOUND', 'Delivery 不存在', 404)
    if (delivery.status === ('delivering' satisfies DeliveryStatus)) {
      return errorResponse('DELIVERY_IN_FLIGHT', 'Delivery 正在投递中，请等待租约过期后再重试', 409)
    }
    delivery.status = 'pending'
    delivery.redeliveryCount += 1
    delivery.updatedAt = new Date().toISOString()
    const { latestAttempt: _latestAttempt, ...rest } = delivery
    return successResponse(rest)
  }),
]
