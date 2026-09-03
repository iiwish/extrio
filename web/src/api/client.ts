import i18next from 'i18next'

import type {
  BatchCollectorImportResult,
  AuthLoginInput,
  AuthSetupInput,
  AuthState,
  CandidateRuleEditInput,
  CollectorDetail,
  CollectorPage,
  CollectionPolicyInput,
  CollectorScheduleInput,
  CreateCollectorInput,
  CreateCollectorsInput,
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
  PlatformError,
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

export interface ItemsExportQuery {
  format: ExportFormat
  collectorId?: string
  runId?: string
  decision?: string
  entityKey?: string
}

export async function exportItemsDownload(query: ItemsExportQuery): Promise<Blob> {
  const params = new URLSearchParams({ format: query.format })
  for (const key of ['collectorId', 'runId', 'decision', 'entityKey'] as const) {
    const value = query[key]?.trim()
    if (value) params.set(key, value)
  }
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
  collectors: () => request<CollectorPage>('/collectors').then((result) => result.items),
  collector: (id: string) => request<CollectorDetail>(`/collectors/${id}`),
  createCollector: (input: CreateCollectorInput) =>
    command<CollectorDetail>('/collectors', { body: JSON.stringify(input) }),
  updateCollector: (id: string, input: UpdateCollectorInput) =>
    command<CollectorDetail>(`/collectors/${id}`, { method: 'PATCH', body: JSON.stringify(input) }),
  createCollectors: (input: CreateCollectorsInput) =>
    command<BatchCollectorImportResult>('/collectors/batch', { body: JSON.stringify(input) }),
  startExploration: (id: string) => command<Operation>(`/collectors/${id}/explorations`),
  saveCollectionPolicy: (id: string, input: CollectionPolicyInput) =>
    command<CollectorDetail>(`/collectors/${id}/collection-policy`, { body: JSON.stringify(input) }),
  updateCollectorSchedule: (id: string, input: CollectorScheduleInput) =>
    command<CollectorDetail>(`/collectors/${id}/schedule`, { method: 'PUT', body: JSON.stringify(input) }),
  updateCandidateRule: (id: string, input: CandidateRuleEditInput) =>
    command<CollectorDetail>(`/collectors/${id}/candidate-rule`, { method: 'PATCH', body: JSON.stringify(input) }),
  operation: (id: string) => request<Operation>(`/operations/${id}`),
  publish: (id: string, reviewDecisions: Record<string, FieldReviewDecision>) =>
    command<CollectorDetail>(`/collectors/${id}/publish`, { body: JSON.stringify({ reviewDecisions }) }),
  startRun: (id: string) => command<Operation>(`/collectors/${id}/runs`),
  runs: () => request<RunPage>('/runs?limit=200').then((result) => result.items),
  runDetail: (id: string) => request<Run>(`/runs/${id}`),
  aiRuns: (collectorId?: string) => request<AiRunPage>(`/ai-runs?limit=200${collectorId ? `&collectorId=${encodeURIComponent(collectorId)}` : ''}`).then((result) => result.items),
  aiRunDetail: (id: string) => request<AiRunDetail>(`/ai-runs/${id}`),
  items: () => request<ItemPage>('/items?limit=200').then((result) => result.items),
  itemsPage: (query: { limit?: number; cursor?: string } = {}) => {
    const params = new URLSearchParams({ limit: String(query.limit ?? 50) })
    if (query.cursor) params.set('cursor', query.cursor)
    return request<ItemPage>(`/items?${params.toString()}`)
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
