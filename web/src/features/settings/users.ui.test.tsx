import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError, api } from '@/api/client'
import { seedCollectors } from '@/api/fixtures'
import type { AuthState, User } from '@/api/types'
import { AppShell } from '@/app/app-shell'
import { AuthGate } from '@/features/auth/auth-gate'
import { CollectorPage } from '@/features/collectors/collector-page'
import { ModelSettingsPage } from './model-settings-page'

window.HTMLElement.prototype.hasPointerCapture = () => false
window.HTMLElement.prototype.releasePointerCapture = () => undefined
window.HTMLElement.prototype.scrollIntoView = () => undefined

const seededUsers: User[] = [
  {
    id: 'user_mock_admin',
    username: 'admin',
    displayName: '林然',
    role: 'administrator',
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

function renderSettingsPage(children = <ModelSettingsPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>,
  )
}

function authenticatedState(role: User['role']): AuthState {
  return {
    authEnabled: true,
    setupRequired: false,
    authenticated: true,
    user: { id: 'user_session', username: 'session-user', displayName: '会话用户', role },
  }
}

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('Settings 用户管理', () => {
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

  it('renders the seeded team accounts with roles, status, and update time', async () => {
    vi.spyOn(api, 'users').mockResolvedValue(seededUsers)
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)

    renderSettingsPage()

    await screen.findByText('陈曦')
    const section = screen.getByRole('region', { name: '用户列表' })
    expect(section).toHaveTextContent('用户管理')
    expect(section).toHaveTextContent('admin')
    expect(section).toHaveTextContent('engineer')
    expect(section).toHaveTextContent('采集工程师')
    expect(section).toHaveTextContent('规则审核员')
    expect(section).toHaveTextContent('数据消费者')
    expect(section).toHaveTextContent('已启用')
    expect(section).toHaveTextContent('已停用')
    expect(section).toHaveTextContent('2026-09-02')
  })

  it('creates a user through the add dialog with the selected role', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'users').mockResolvedValue(seededUsers)
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)
    const created: User = {
      id: 'user_created',
      username: 'new_engineer',
      displayName: '新工程师',
      role: 'reviewer',
      enabled: true,
      createdAt: '2026-09-03T01:00:00.000Z',
      updatedAt: '2026-09-03T01:00:00.000Z',
    }
    const create = vi.spyOn(api, 'createUser').mockResolvedValue(created)

    renderSettingsPage()
    await screen.findByRole('region', { name: '用户列表' })

    await user.click(screen.getByRole('button', { name: '添加用户' }))
    await user.type(screen.getByLabelText('用户名'), 'new_engineer')
    await user.type(screen.getByLabelText('显示名称'), '新工程师')
    await user.type(screen.getByLabelText('初始密码'), 'initial-pass-1')
    expect(screen.getByLabelText('初始密码')).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('combobox', { name: '角色' }))
    await user.click(await screen.findByRole('option', { name: '规则审核员' }))
    await user.click(screen.getByRole('button', { name: '创建用户' }))

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(create.mock.calls[0][0]).toEqual({
      username: 'new_engineer',
      password: 'initial-pass-1',
      displayName: '新工程师',
      role: 'reviewer',
    })
  })

  it('maps USERNAME_TAKEN to the localized duplicate-username message', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'users').mockResolvedValue(seededUsers)
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)
    vi.spyOn(api, 'createUser').mockRejectedValue(new ApiRequestError({
      code: 'USERNAME_TAKEN',
      message: 'duplicate username',
      requestId: 'req_duplicate_user',
      retryable: false,
    }))

    renderSettingsPage()
    await screen.findByRole('region', { name: '用户列表' })

    await user.click(screen.getByRole('button', { name: '添加用户' }))
    await user.type(screen.getByLabelText('用户名'), 'engineer')
    await user.type(screen.getByLabelText('初始密码'), 'initial-pass-1')
    await user.click(screen.getByRole('button', { name: '创建用户' }))

    expect(await screen.findByText('用户名已存在')).toBeInTheDocument()
  })

  it('disables role and enabled controls for the last active administrator row', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'users').mockResolvedValue(seededUsers)
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)

    renderSettingsPage()
    await screen.findByText('陈曦')

    expect(await screen.findByRole('button', { name: '停用用户 admin' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '停用用户 engineer' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '编辑用户 admin' }))
    expect(screen.getByRole('combobox', { name: '角色' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: '启用此账号' })).toBeDisabled()
    expect(screen.getByText('系统至少保留一个可用的管理员账号')).toBeInTheDocument()
  })

  it('hides user management for non-administrator sessions', async () => {
    vi.spyOn(api, 'authState').mockResolvedValue(authenticatedState('viewer'))
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(configuration)

    renderSettingsPage(<AuthGate><ModelSettingsPage /></AuthGate>)

    expect(await screen.findByText('OpenAI')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '用户列表' })).not.toBeInTheDocument()
    expect(screen.queryByText('用户管理')).not.toBeInTheDocument()
  })
})

describe('Role surfaces in the console chrome', () => {
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

  it('shows the signed-in role label in the topbar pill', async () => {
    vi.spyOn(api, 'authState').mockResolvedValue(authenticatedState('reviewer'))

    render(
      <MemoryRouter>
        <AuthGate><AppShell /></AuthGate>
      </MemoryRouter>,
    )

    const pill = await screen.findByText('规则审核员')
    expect(pill).toHaveClass('role-pill')
  })

  it('locks rule publication for the engineer role with an explanatory hint', async () => {
    vi.spyOn(api, 'authState').mockResolvedValue(authenticatedState('engineer'))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === '/api/v1/collectors/collector_beijing_tender') return jsonResponse(seedCollectors[0])
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      return jsonResponse({ code: 'NOT_FOUND', message: 'missing', requestId: 'req_missing', retryable: false }, 404)
    }))

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/collectors/collector_beijing_tender']}>
          <AuthGate>
            <Routes>
              <Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}>
                <Route path="/collectors/:collectorId" element={<CollectorPage />} />
              </Route>
            </Routes>
          </AuthGate>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const publishButton = await screen.findByRole('button', { name: '审核并发布' })
    expect(publishButton).toBeDisabled()
    expect(publishButton).toHaveAttribute('title', '当前角色无权发布规则，需规则审核员或管理员')
  })

  it('keeps rule publication unlocked for administrators', async () => {
    vi.spyOn(api, 'authState').mockResolvedValue(authenticatedState('administrator'))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === '/api/v1/collectors/collector_beijing_tender') return jsonResponse(seedCollectors[0])
      if (path === '/api/v1/ai-runs') return jsonResponse({ items: [], page: { nextCursor: null } })
      return jsonResponse({ code: 'NOT_FOUND', message: 'missing', requestId: 'req_missing', retryable: false }, 404)
    }))

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/collectors/collector_beijing_tender']}>
          <AuthGate>
            <Routes>
              <Route element={<Outlet context={{ setTopbarBackTarget: vi.fn() }} />}>
                <Route path="/collectors/:collectorId" element={<CollectorPage />} />
              </Route>
            </Routes>
          </AuthGate>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const publishButton = await screen.findByRole('button', { name: '审核并发布' })
    expect(publishButton).not.toHaveAttribute('title', '当前角色无权发布规则，需规则审核员或管理员')
  })
})
