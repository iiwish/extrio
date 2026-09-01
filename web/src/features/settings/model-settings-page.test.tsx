import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import type { ModelConfiguration } from '@/api/types'
import { ModelSettingsPage, providerPreset } from './model-settings-page'

vi.stubGlobal('ResizeObserver', class {
  observe() { return undefined }
  unobserve() { return undefined }
  disconnect() { return undefined }
})

const configuration: ModelConfiguration = {
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

describe('ModelSettingsPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('uses provider endpoint presets without presetting a credential', () => {
    expect(providerPreset('deepseek')).toMatchObject({
      baseUrl: 'https://api.deepseek.com/v1',
    })
    expect(providerPreset('deepseek')).not.toHaveProperty('apiKey')
  })

  it('groups models under their provider and saves a default model', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)
    const update = vi.spyOn(api, 'updateModelConfiguration').mockImplementation(async (input) => ({
      providers: input.providers.map((provider) => ({
        id: provider.id,
        name: provider.name,
        provider: provider.provider,
        baseUrl: provider.baseUrl,
        enabled: provider.enabled,
        credentialConfigured: Boolean(provider.apiKey) || configuration.providers[0].credentialConfigured,
        updatedAt: '2026-08-31T10:00:00Z',
      })),
      models: input.models.map((model) => ({ ...model, isDefault: model.id === input.defaultModelId, updatedAt: '2026-08-31T10:00:00Z' })),
      defaultModelId: input.defaultModelId,
      updatedAt: '2026-08-31T10:00:00Z',
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

    render(<QueryClientProvider client={client}><MemoryRouter><ModelSettingsPage /></MemoryRouter></QueryClientProvider>)

    const providerGroup = await screen.findByRole('region', { name: 'OpenAI 供应商' })
    const toolbar = screen.getByLabelText('模型配置概况')
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    expect(within(toolbar).getByText('默认模型')).toBeInTheDocument()
    expect(within(toolbar).queryByText('供应商', { exact: true })).not.toBeInTheDocument()
    expect(within(toolbar).queryByText('可用模型', { exact: true })).not.toBeInTheDocument()
    expect(within(providerGroup).getByText('暂无模型')).toBeInTheDocument()
    await user.click(within(providerGroup).getByRole('button', { name: 'OpenAI 供应商操作' }))
    await user.click(screen.getByRole('menuitem', { name: '编辑供应商' }))
    const apiKey = screen.getByLabelText('API 密钥')
    expect(apiKey).toHaveAttribute('type', 'password')
    await user.type(apiKey, 'sk-test-browser-only')
    await user.click(screen.getByRole('button', { name: '保存供应商' }))
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(update.mock.calls[0][0]).toEqual(expect.objectContaining({
      providers: [expect.objectContaining({ apiKey: 'sk-test-browser-only' })],
    }))

    await user.click(within(providerGroup).getByRole('button', { name: '添加模型' }))
    await user.type(screen.getByLabelText('模型 ID'), 'gpt-4.1-mini')
    await user.click(screen.getByRole('button', { name: '保存模型' }))

    await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
    expect(update.mock.calls[1][0]).toEqual(expect.objectContaining({
      defaultModelId: expect.stringMatching(/^model_/),
      models: [expect.objectContaining({ providerId: 'provider_openai', modelId: 'gpt-4.1-mini' })],
    }))
  })
})
