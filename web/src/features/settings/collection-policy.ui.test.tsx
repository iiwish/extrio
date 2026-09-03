import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError, api } from '@/api/client'
import type { AuthState, PlatformSettings, User } from '@/api/types'
import { AuthGate } from '@/features/auth/auth-gate'
import { ModelSettingsPage } from './model-settings-page'

window.HTMLElement.prototype.hasPointerCapture = () => false
window.HTMLElement.prototype.releasePointerCapture = () => undefined
window.HTMLElement.prototype.scrollIntoView = () => undefined

const configuration = {
  providers: [{
    id: 'provider_openai',
    name: 'OpenAI',
    provider: 'openai' as const,
    baseUrl: 'https://api.openai.com/v1',
    enabled: true,
    credentialConfigured: false,
    updatedAt: null,
  }],
  models: [],
  defaultModelId: null,
  updatedAt: null,
}

const seededUsers: User[] = []

function platformSettings(allowAnonymousHttp: boolean): PlatformSettings {
  return { allowAnonymousHttp, updatedBy: null, updatedAt: null }
}

function authenticatedState(role: User['role']): AuthState {
  return {
    authEnabled: true,
    setupRequired: false,
    authenticated: true,
    user: { id: 'user_session', username: 'session-user', displayName: '会话用户', role },
  }
}

function renderSettingsPage(children = <ModelSettingsPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Settings 采集策略', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class {
      observe() { return undefined }
      unobserve() { return undefined }
      disconnect() { return undefined }
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('renders the toggle checked by default for administrators', async () => {
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)
    vi.spyOn(api, 'users').mockResolvedValue(seededUsers)
    vi.spyOn(api, 'platformSettings').mockResolvedValue(platformSettings(true))

    renderSettingsPage()

    const section = await screen.findByRole('region', { name: '采集策略' })
    expect(section).toHaveTextContent('采集策略')
    expect(section).toHaveTextContent('允许创建以 http:// 开头的匿名采集来源')
    expect(await screen.findByRole('switch', { name: '允许匿名 HTTP 来源' })).toBeChecked()
  })

  it('saves the flipped policy and reflects the updated state', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)
    vi.spyOn(api, 'users').mockResolvedValue(seededUsers)
    vi.spyOn(api, 'platformSettings').mockResolvedValue(platformSettings(true))
    const update = vi.spyOn(api, 'updatePlatformSettings').mockImplementation(async (input) => platformSettings(input.allowAnonymousHttp))

    renderSettingsPage()
    const toggle = await screen.findByRole('switch', { name: '允许匿名 HTTP 来源' })

    await user.click(toggle)

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(update.mock.calls[0][0]).toEqual({ allowAnonymousHttp: false })
    await waitFor(() => expect(screen.getByRole('switch', { name: '允许匿名 HTTP 来源' })).not.toBeChecked())
  })

  it('maps a 403 to the localized message and keeps the previous state', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)
    vi.spyOn(api, 'users').mockResolvedValue(seededUsers)
    vi.spyOn(api, 'platformSettings').mockResolvedValue(platformSettings(true))
    vi.spyOn(api, 'updatePlatformSettings').mockRejectedValue(new ApiRequestError({
      code: 'FORBIDDEN',
      message: 'forbidden',
      requestId: 'req_policy_forbidden',
      retryable: false,
    }))

    renderSettingsPage()
    const toggle = await screen.findByRole('switch', { name: '允许匿名 HTTP 来源' })

    await user.click(toggle)

    expect(await screen.findByText('当前角色无权执行该操作')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '允许匿名 HTTP 来源' })).toBeChecked()
  })

  it('hides collection policy for non-administrator sessions', async () => {
    vi.spyOn(api, 'authState').mockResolvedValue(authenticatedState('viewer'))
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)
    const platformSettingsQuery = vi.spyOn(api, 'platformSettings')

    renderSettingsPage(<AuthGate><ModelSettingsPage /></AuthGate>)

    expect(await screen.findByText('OpenAI')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '采集策略' })).not.toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: '允许匿名 HTTP 来源' })).not.toBeInTheDocument()
    expect(platformSettingsQuery).not.toHaveBeenCalled()
  })
})
