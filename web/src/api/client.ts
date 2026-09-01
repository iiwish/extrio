import type {
  BatchCollectorImportResult,
  CandidateRuleEditInput,
  CollectorDetail,
  CollectorPage,
  CollectionPolicyInput,
  CollectorScheduleInput,
  CreateCollectorInput,
  CreateCollectorsInput,
  FieldReviewDecision,
  HarvestItem,
  ItemPage,
  ModelConfiguration,
  ModelConfigurationInput,
  ModelSetting,
  ModelSettingInput,
  Operation,
  PlatformError,
  Run,
  RunPage,
  UpdateCollectorInput,
} from './types'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
export const API_BASE_URL = (configuredBaseUrl || '/api/v1').replace(/\/$/, '')

export function apiEnvironmentLabel() {
  return import.meta.env.VITE_ENABLE_MOCKS === 'true' ? 'Mock 合同环境' : '真实 API 模式'
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
      message: '无法连接控制面，请确认本地 API 已启动或启用 Mock 合同环境',
      requestId: 'request_id_unavailable',
      retryable: true,
    })
  }
  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as PlatformError | null
    throw new ApiRequestError(error ?? {
      code: 'UNEXPECTED_RESPONSE',
      message: response.status === 502 || response.status === 503
        ? '控制面暂不可用，请确认本地 API 已启动或启用 Mock 合同环境'
        : '请求失败，请稍后重试',
      requestId: response.headers.get('X-Request-ID') ?? 'request_id_unavailable',
      retryable: response.status >= 500,
    })
  }
  return response.json() as Promise<T>
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
      message: `异步任务终态：${operation.status}`,
      requestId: 'operation_request_id_unavailable',
      retryable: false,
    })
  }
  return operation
}

export const api = {
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
  items: () => request<ItemPage>('/items?limit=200').then((result) => result.items),
  item: (id: string) => request<HarvestItem>(`/items/${id}`),
}
