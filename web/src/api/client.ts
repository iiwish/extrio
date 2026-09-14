import i18next from 'i18next'

import type {
  Overview,
  Collection,
  CollectionDetail,
  CollectionInput,
  CollectionUpdateInput,
  CollectionVersion,
  CollectionVersionPublishInput,
  CollectionVersionList,
  CollectionTemplateList,
  FieldSuggestion,
  FieldSuggestionList,
  FieldSuggestionInput,
  ApplyTemplateInput,
  ApplySuggestionInput,
  CollectionMigrationPlan,
  CollectionMigrationInput,
  CancelCollectionMigrationInput,
  BatchCollectorImportResult,
  AuthLoginInput,
  AuthSetupInput,
  AuthState,
  CandidateRuleEditInput,
  CollectorDetail,
  CollectorLifecyclePlan,
  CollectorLifecycleInput,
  CollectorLifecycleResult,
  CollectorReassignmentPlan,
  CollectorReassignmentInput,
  CollectorPage,
  CollectionPolicyInput,
  CollectorScheduleInput,
  CreateCollectorInput,
  CreateCollectorsInput,
  ExplorationInput,
  CreateUserInput,
  UpdateUserInput,
  User,
  UserPage,
  Delivery,
  DeliveryDetail,
  DeliveryPage,
  ExportFormat,
  FieldReviewDecision,
  HarvestItem,
  AiRunDetail,
  AiRunPage,
  ItemPage,
  ModelConfiguration,
  ModelConfigurationInput,
  ModelSetting,
  ModelSettingInput,
  Operation,
  RuntimeDiagnostics,
  RunEvidenceStatus,
  PlatformError,
  PlatformSettings,
  PlatformSettingsInput,
  RepairInput,
  Run,
  RunPage,
  Sink,
  SinkInput,
  SinkPage,
  SinkUpdateInput,
  UpdateCollectorInput,
} from './types'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
export const API_BASE_URL = (configuredBaseUrl || '/api/v1').replace(/\/$/, '')

export function apiEnvironmentLabel() {
  return import.meta.env.VITE_ENABLE_MOCKS === 'true'
    ? i18next.t('api:environment.mock')
    : i18next.t('api:environment.live')
}

export class ApiRequestError extends Error {
  code: string
  requestId: string
  retryable: boolean
  pointer?: string | null

  constructor(error: PlatformError) {
    super(error.message)
    this.name = 'ApiRequestError'
    this.code = error.code
    this.requestId = error.requestId
    this.retryable = error.retryable
    this.pointer = error.pointer
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: 'include',
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        Accept: 'application/json',
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiRequestError({
      code: 'UNEXPECTED_RESPONSE',
      message: i18next.t('api:error.connectionFailed'),
      requestId: 'request_id_unavailable',
      retryable: true,
    })
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/')) {
      window.dispatchEvent(new Event('extrio:auth-required'))
    }
    const error = (await response.json().catch(() => null)) as PlatformError | null
    throw new ApiRequestError(error ?? {
      code: 'UNEXPECTED_RESPONSE',
      message: response.status === 502 || response.status === 503
        ? i18next.t('api:error.controlPlaneUnavailable')
        : i18next.t('api:error.requestFailed'),
      requestId: response.headers.get('X-Request-ID') ?? 'request_id_unavailable',
      retryable: response.status >= 500,
    })
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function requestError(response: Response): ApiRequestError {
  return new ApiRequestError({
    code: 'UNEXPECTED_RESPONSE',
    message: response.status === 502 || response.status === 503
      ? i18next.t('api:error.controlPlaneUnavailable')
      : i18next.t('api:error.requestFailed'),
    requestId: response.headers.get('X-Request-ID') ?? 'request_id_unavailable',
    retryable: response.status >= 500,
  })
}

export interface ItemsQuery {
  view?: 'observations' | 'entities'
  collectorId?: string
  runId?: string
  decision?: string
  entityKey?: string
  sourceHost?: string
  q?: string
}

export interface ItemsExportQuery extends ItemsQuery {
  format: ExportFormat
}

function itemQueryParams(query: ItemsQuery) {
  const params = new URLSearchParams()
  for (const key of ['view', 'collectorId', 'runId', 'decision', 'entityKey', 'sourceHost', 'q'] as const) {
    const value = query[key]?.trim()
    if (value) params.set(key, value)
  }
  return params
}

export async function exportItemsDownload(query: ItemsExportQuery): Promise<Blob> {
  const params = itemQueryParams(query)
  params.set('format', query.format)
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/items/export?${params.toString()}`, {
      credentials: 'include',
      headers: { Accept: query.format === 'csv' ? 'text/csv' : 'application/x-ndjson' },
    })
  } catch {
    throw new ApiRequestError({
      code: 'UNEXPECTED_RESPONSE',
      message: i18next.t('api:error.connectionFailed'),
      requestId: 'request_id_unavailable',
      retryable: true,
    })
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('extrio:auth-required'))
    const error = (await response.json().catch(() => null)) as PlatformError | null
    throw error ? new ApiRequestError(error) : requestError(response)
  }
  return response.blob()
}

export interface EvidenceBundleQuery {
  since?: string
  until?: string
  ruleVersionId?: string
}

export async function downloadEvidenceBundle(collectorId: string, query: EvidenceBundleQuery = {}): Promise<Blob> {
  const params = new URLSearchParams()
  for (const key of ['since', 'until', 'ruleVersionId'] as const) {
    const value = query[key]?.trim()
    if (value) params.set(key, value)
  }
  const scope = params.size > 0 ? `?${params.toString()}` : ''
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/collectors/${encodeURIComponent(collectorId)}/evidence-bundle${scope}`, {
      credentials: 'include',
      headers: { Accept: 'application/zip' },
    })
  } catch {
    throw new ApiRequestError({
      code: 'UNEXPECTED_RESPONSE',
      message: i18next.t('api:error.connectionFailed'),
      requestId: 'request_id_unavailable',
      retryable: true,
    })
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('extrio:auth-required'))
    const error = (await response.json().catch(() => null)) as PlatformError | null
    throw error ? new ApiRequestError(error) : requestError(response)
  }
  return response.blob()
}

function idempotencyKey() {
  return crypto.randomUUID()
}

function command<T>(path: string, init?: RequestInit) {
  return request<T>(path, {
    ...init,
    method: init?.method ?? 'POST',
    headers: { 'Idempotency-Key': idempotencyKey(), ...init?.headers },
  })
}

function sleep(duration: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Operation polling aborted', 'AbortError'))
      return
    }
    const timeout = window.setTimeout(resolve, duration)
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timeout)
      reject(new DOMException('Operation polling aborted', 'AbortError'))
    }, { once: true })
  })
}

export async function waitForOperation(
  accepted: Operation,
  onUpdate: (operation: Operation) => void,
  signal?: AbortSignal,
) {
  let operation = accepted
  onUpdate(operation)
  while (!['succeeded', 'failed', 'cancelled', 'timed_out'].includes(operation.status)) {
    await sleep(operation.pollAfterMs, signal)
    operation = await api.operation(operation.id)
    onUpdate(operation)
  }
  if (operation.status !== 'succeeded') {
    const terminalCode = operation.status === 'cancelled' ? 'OPERATION_CANCELLED' : operation.status === 'timed_out' ? 'OPERATION_TIMED_OUT' : 'INTERNAL_ERROR'
    throw new ApiRequestError(operation.error ?? {
      code: terminalCode,
      message: i18next.t('api:error.operationTerminal', { status: operation.status }),
      requestId: 'operation_request_id_unavailable',
      retryable: false,
    })
  }
  return operation
}

export const api = {
  overview: (timezone = Intl.DateTimeFormat().resolvedOptions().timeZone) => request<Overview>(`/overview?timezone=${encodeURIComponent(timezone)}`),
  collections: () => request<{ items: Collection[]; total: number }>('/collections').then((result) => result.items),
  collectionTemplates: () => request<CollectionTemplateList>('/collection-templates').then((result) => result.items),
  applyCollectionTemplate: (id: string, input: ApplyTemplateInput) => command<Collection>(`/collections/${encodeURIComponent(id)}/apply-template`, { body: JSON.stringify(input) }),
  fieldSuggestions: (id: string) => request<FieldSuggestionList>(`/collections/${encodeURIComponent(id)}/field-suggestions`).then((result) => result.items),
  startFieldSuggestion: (id: string, input: FieldSuggestionInput) => command<FieldSuggestion>(`/collections/${encodeURIComponent(id)}/field-suggestions`, { body: JSON.stringify(input) }),
  applyFieldSuggestion: (id: string, suggestionId: string, input: ApplySuggestionInput) => command<Collection>(`/collections/${encodeURIComponent(id)}/field-suggestions/${encodeURIComponent(suggestionId)}/apply`, { body: JSON.stringify(input) }),
  collectionMigrationPlan: (id: string, targetVersionId: string) => request<CollectionMigrationPlan>(`/collectors/${encodeURIComponent(id)}/collection-migration?targetVersionId=${encodeURIComponent(targetVersionId)}`),
  migrateCollectionVersion: (id: string, input: CollectionMigrationInput) => command<CollectorDetail>(`/collectors/${encodeURIComponent(id)}/collection-migration`, { body: JSON.stringify(input) }),
  cancelCollectionMigration: (id: string, input: CancelCollectionMigrationInput) => command<CollectorDetail>(`/collectors/${encodeURIComponent(id)}/collection-migration/cancel`, { body: JSON.stringify(input) }),
  collection: (id: string) => request<CollectionDetail>(`/collections/${encodeURIComponent(id)}`),
  createCollection: (input: CollectionInput, key?: string) => command<Collection>('/collections', {
    body: JSON.stringify(input), ...(key ? { headers: { 'Idempotency-Key': key } } : {}),
  }),
  updateCollection: (id: string, input: CollectionUpdateInput) => command<Collection>(`/collections/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(input) }),
  deleteCollection: (id: string, revision: number) => command<{ id: string; deleted: true }>(`/collections/${encodeURIComponent(id)}`, { method: 'DELETE', body: JSON.stringify({ revision }) }),
  publishCollectionVersion: (id: string, input: CollectionVersionPublishInput, key?: string) =>
    command<CollectionVersion>(`/collections/${encodeURIComponent(id)}/publish-version`, {
      method: 'POST',
      body: JSON.stringify(input),
      ...(key ? { headers: { 'Idempotency-Key': key } } : {}),
    }),
  collectionVersions: (id: string) =>
    request<CollectionVersionList>(`/collections/${encodeURIComponent(id)}/versions`),
  collectionVersion: (collectionId: string, versionId: string) =>
    request<CollectionVersion>(`/collections/${encodeURIComponent(collectionId)}/versions/${encodeURIComponent(versionId)}`),
  authState: () => request<AuthState>('/auth/state'),
  setupAuth: (input: AuthSetupInput) => request<AuthState>('/auth/setup', { method: 'POST', body: JSON.stringify(input) }),
  login: (input: AuthLoginInput) => request<AuthState>('/auth/login', { method: 'POST', body: JSON.stringify(input) }),
  logout: () => request<{ authenticated: false }>('/auth/logout', { method: 'POST' }),
  users: () => request<UserPage>('/users').then((result) => result.items),
  createUser: (input: CreateUserInput) => command<User>('/users', { body: JSON.stringify(input) }),
  updateUser: (userId: string, input: UpdateUserInput) =>
    command<User>(`/users/${userId}`, { method: 'PATCH', body: JSON.stringify(input) }),
  modelConfiguration: () => request<ModelConfiguration>('/settings/models'),
  updateModelConfiguration: (input: ModelConfigurationInput) =>
    command<ModelConfiguration>('/settings/models', { method: 'PUT', body: JSON.stringify(input) }),
  modelSetting: () => request<ModelSetting>('/settings/model'),
  updateModelSetting: (input: ModelSettingInput) =>
    command<ModelSetting>('/settings/model', { method: 'PUT', body: JSON.stringify(input) }),
  platformSettings: () => request<PlatformSettings>('/settings/platform'),
  updatePlatformSettings: (input: PlatformSettingsInput) =>
    command<PlatformSettings>('/settings/platform', { method: 'PUT', body: JSON.stringify(input) }),
  collectors: (lifecycle: 'active' | 'archived' | 'all' = 'active') => request<CollectorPage>(lifecycle === 'active' ? '/collectors' : `/collectors?lifecycle=${lifecycle}`).then((result) => result.items),
  collectorLifecyclePlan: (id: string) => request<CollectorLifecyclePlan>(`/collectors/${encodeURIComponent(id)}/lifecycle`),
  changeCollectorLifecycle: (id: string, input: CollectorLifecycleInput, key: string) => command<CollectorLifecycleResult>(`/collectors/${encodeURIComponent(id)}/lifecycle`, { body: JSON.stringify(input), headers: { 'Idempotency-Key': key } }),
  collectorReassignmentPlan: (id: string, target: string) => request<CollectorReassignmentPlan>(`/collectors/${encodeURIComponent(id)}/reassignment?targetCollectionId=${encodeURIComponent(target)}`),
  reassignCollector: (id: string, input: CollectorReassignmentInput, key: string) => command<CollectorDetail>(`/collectors/${encodeURIComponent(id)}/reassignment`, { body: JSON.stringify(input), headers: { 'Idempotency-Key': key } }),
  collector: (id: string) => request<CollectorDetail>(`/collectors/${id}`),
  createCollector: (input: CreateCollectorInput) =>
    command<CollectorDetail>('/collectors', { body: JSON.stringify(input) }),
  updateCollector: (id: string, input: UpdateCollectorInput, key?: string) =>
    command<CollectorDetail>(`/collectors/${id}`, { method: 'PATCH', body: JSON.stringify(input), ...(key ? { headers: { 'Idempotency-Key': key } } : {}) }),
  createCollectors: (input: CreateCollectorsInput, key?: string) =>
    command<BatchCollectorImportResult>('/collectors/batch', { body: JSON.stringify(input), ...(key ? { headers: { 'Idempotency-Key': key } } : {}) }),
  startExploration: (id: string, input: ExplorationInput = {}) =>
    command<Operation>(`/collectors/${id}/explorations`, { body: JSON.stringify(input) }),
  startRepair: (id: string, input: RepairInput = {}) =>
    command<Operation>(`/collectors/${id}/repairs`, { body: JSON.stringify(input) }),
  saveCollectionPolicy: (id: string, input: CollectionPolicyInput) =>
    command<CollectorDetail>(`/collectors/${id}/collection-policy`, { body: JSON.stringify(input) }),
  updateCollectorSchedule: (id: string, input: CollectorScheduleInput) =>
    command<CollectorDetail>(`/collectors/${id}/schedule`, { method: 'PUT', body: JSON.stringify(input) }),
  updateCandidateRule: (id: string, input: CandidateRuleEditInput) =>
    command<CollectorDetail>(`/collectors/${id}/candidate-rule`, { method: 'PATCH', body: JSON.stringify(input) }),
  operation: (id: string) => request<Operation>(`/operations/${id}`),
  cancelOperation: (id: string) => command<Operation>(`/operations/${encodeURIComponent(id)}/cancel`),
  runtime: () => request<RuntimeDiagnostics>('/runtime'),
  runEvidence: (id: string) => request<RunEvidenceStatus>(`/runs/${encodeURIComponent(id)}/evidence`),
  publish: (id: string, reviewDecisions: Record<string, FieldReviewDecision>) =>
    command<CollectorDetail>(`/collectors/${id}/publish`, { body: JSON.stringify({ reviewDecisions }) }),
  startRun: (id: string) => command<Operation>(`/collectors/${id}/runs`),
  runs: () => request<RunPage>('/runs?limit=200').then((result) => result.items),
  runDetail: (id: string) => request<Run>(`/runs/${id}`),
  aiRuns: (collectorId?: string) => request<AiRunPage>(`/ai-runs?limit=200${collectorId ? `&collectorId=${encodeURIComponent(collectorId)}` : ''}`).then((result) => result.items),
  aiRunDetail: (id: string) => request<AiRunDetail>(`/ai-runs/${id}`),
  items: () => request<ItemPage>('/items?limit=200').then((result) => result.items),
  itemsPage: (query: ItemsQuery & { limit?: number; cursor?: string } = {}, signal?: AbortSignal) => {
    const params = itemQueryParams(query)
    params.set('limit', String(query.limit ?? 50))
    if (query.cursor) params.set('cursor', query.cursor)
    return request<ItemPage>(`/items?${params.toString()}`, { signal })
  },
  item: (id: string) => request<HarvestItem>(`/items/${id}`),
  sinks: (collectorId: string) =>
    request<SinkPage>(`/collectors/${collectorId}/sinks`).then((result) => result.items),
  createSink: (collectorId: string, input: SinkInput) =>
    command<Sink>(`/collectors/${collectorId}/sinks`, { body: JSON.stringify(input) }),
  updateSink: (collectorId: string, sinkId: string, input: SinkUpdateInput) =>
    command<Sink>(`/collectors/${collectorId}/sinks/${sinkId}`, { method: 'PUT', body: JSON.stringify(input) }),
  deleteSink: (collectorId: string, sinkId: string) =>
    command<void>(`/collectors/${collectorId}/sinks/${sinkId}`, { method: 'DELETE' }),
  testSink: (collectorId: string, sinkId: string) =>
    command<Delivery>(`/collectors/${collectorId}/sinks/${sinkId}/test`),
  deliveries: (collectorId: string) =>
    request<DeliveryPage>(`/collectors/${collectorId}/deliveries`).then((result) => result.items),
  delivery: (id: string) => request<DeliveryDetail>(`/deliveries/${id}`),
  redeliverDelivery: (id: string) => command<Delivery>(`/deliveries/${id}/redeliver`),
}
