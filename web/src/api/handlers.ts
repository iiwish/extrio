import { delay, http, HttpResponse } from 'msw'
import { collectionPolicyFor, createCandidateRule, createItemsForCollector, scheduleFor, seedCollectors, seedRuns } from './fixtures'
import type {
  BatchCollectorImportItem,
  CandidateRuleEditInput,
  CollectorDetail,
  CollectorScheduleInput,
  CollectionPolicyInput,
  CreateCollectorInput,
  CreateCollectorsInput,
  FieldReviewDecision,
  ModelConfiguration,
  ModelConfigurationInput,
  ModelSetting,
  ModelSettingInput,
  Operation,
  PlatformError,
  Run,
  UpdateCollectorInput,
} from './types'

const collectors = structuredClone(seedCollectors)
const runs = structuredClone(seedRuns)
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

  if (operation.value.kind === 'run' && snapshot.phase !== 'completed') {
    const activeRun = byId(runs, operation.value.resourceId)
    if (activeRun) activeRun.status = snapshot.phase === 'finalizing' ? 'finalizing' : 'running'
  }

  if (snapshot.phase !== 'completed' || operation.finalized) return
  operation.finalized = true
  if (operation.value.kind === 'explore') {
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

export const handlers = [
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
    collector.activeOperationId = operation.value.id
    return successResponse(operation.value, 202, { Location: operation.value.statusUrl })
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
  http.get('*/api/v1/items', () => successResponse(page(runs.flatMap((run) => run.items)))),
  http.get('*/api/v1/items/:id', ({ params }) => {
    const item = runs.flatMap((run) => run.items).find((row) => row.id === String(params.id))
    return item ? successResponse(item) : errorResponse('ITEM_NOT_FOUND', 'Item 或拒绝候选不存在', 404)
  }),
]
