import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { handlers } from './handlers'
import type { BatchCollectorImportResult, ModelConfiguration, ModelSetting, Operation, PlatformError } from './types'

const server = setupServer(...handlers)

describe('asynchronous HTTP contract', () => {
  beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
  afterAll(() => server.close())

  it('requires idempotency and reaches a durable terminal Operation', async () => {
    const endpoint = 'http://localhost/api/v1/collectors/collector_beijing_tender/explorations'
    const rejected = await fetch(endpoint, { method: 'POST' })
    const rejectedBody = await rejected.json() as PlatformError
    expect(rejected.status).toBe(400)
    expect(rejectedBody.code).toBe('IDEMPOTENCY_KEY_REQUIRED')
    expect(rejected.headers.get('X-Request-ID')).toBe(rejectedBody.requestId)

    const accepted = await fetch(endpoint, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } })
    let operation = await accepted.json() as Operation
    expect(accepted.status).toBe(202)
    expect(accepted.headers.get('Location')).toBe(operation.statusUrl)
    expect(accepted.headers.get('X-Request-ID')).toBeTruthy()

    const seenStatuses = [operation.status]
    while (!['succeeded', 'failed', 'cancelled', 'timed_out'].includes(operation.status)) {
      const response = await fetch(`http://localhost${operation.statusUrl}`)
      operation = await response.json() as Operation
      seenStatuses.push(operation.status)
      expect(response.headers.get('X-Request-ID')).toBeTruthy()
    }

    expect(seenStatuses[0]).toBe('queued')
    expect(seenStatuses).toContain('running')
    expect(operation.status).toBe('succeeded')
    expect(operation.phase).toBe('completed')
    expect(operation.progress).toBe(100)
  })

  it('handles batch Collector creation in the isolated mock environment', async () => {
    const response = await fetch('http://localhost/api/v1/collectors/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({
        collectionName: '批量请求回归测试',
        intent: '验证新建页面不会绕过 Mock 请求处理器',
        sourceUrls: [`https://batch-${crypto.randomUUID()}.example.gov.cn/notices`],
      }),
    })
    const result = await response.json() as BatchCollectorImportResult

    expect(response.status).toBe(200)
    expect(result.createdCount).toBe(1)
    expect(result.results[0].status).toBe('created')
  })

  it('adds new sources to an existing collection without replacing its definition', async () => {
    const response = await fetch('http://localhost/api/v1/collectors/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({
        collectionId: 'collection_nationwide_tender',
        collectionName: '不会覆盖已有需求',
        intent: '不会覆盖已有采集意图',
        sourceUrls: [`https://existing-${crypto.randomUUID()}.example.gov.cn/notices`],
      }),
    })
    const result = await response.json() as BatchCollectorImportResult

    expect(response.status).toBe(200)
    expect(result.collectionId).toBe('collection_nationwide_tender')
    expect(result.collectionName).toBe('全国公共资源交易标讯')
    expect(result.results[0].collector?.intent).not.toBe('不会覆盖已有采集意图')
  })

  it('saves model metadata without accepting a plaintext credential', async () => {
    const response = await fetch('http://localhost/api/v1/settings/model', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({
        provider: 'deepseek',
        baseUrl: 'https://api.deepseek.com/v1',
        model: 'deepseek-chat',
        secretRef: 'env:EXTRIO_DEEPSEEK_API_KEY',
      }),
    })
    const result = await response.json() as ModelSetting

    expect(response.status).toBe(200)
    expect(result.provider).toBe('deepseek')
    expect(result.secretConfigured).toBe(false)
    expect(JSON.stringify(result)).not.toContain('apiKey')
  })

  it('persists separate provider and model configuration lists', async () => {
    const response = await fetch('http://localhost/api/v1/settings/models', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({
        providers: [{ id: 'provider_openai', name: 'OpenAI', provider: 'openai', baseUrl: 'https://api.openai.com/v1', apiKey: 'sk-mock-contract-test', enabled: true }],
        models: [{ id: 'model_gpt', providerId: 'provider_openai', modelId: 'gpt-4.1-mini', enabled: true }],
        defaultModelId: 'model_gpt',
      }),
    })
    const result = await response.json() as ModelConfiguration

    expect(response.status).toBe(200)
    expect(result.providers).toHaveLength(1)
    expect(result.providers[0].credentialConfigured).toBe(true)
    expect(JSON.stringify(result)).not.toContain('sk-mock-contract-test')
    expect(result.models[0].isDefault).toBe(true)
    expect(result.defaultModelId).toBe('model_gpt')
  })
})
