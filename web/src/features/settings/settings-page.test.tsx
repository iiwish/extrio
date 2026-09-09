import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { AuthGate } from '@/features/auth/auth-gate'
import { SettingsPage } from './settings-page'

function LocationState() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><output aria-label="route">{location.search}</output><button onClick={() => navigate(-1)}>History back</button></>
}
function mount(path = '/settings', authenticated = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const page = <><SettingsPage /><LocationState /></>
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{authenticated ? <AuthGate>{page}</AuthGate> : page}</MemoryRouter></QueryClientProvider>)
}
beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.spyOn(api, 'platformSettings').mockResolvedValue({ allowAnonymousHttp: true, updatedAt: null, updatedBy: null })
  vi.spyOn(api, 'users').mockResolvedValue([])
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const empty = { providers: [], models: [], defaultModelId: null, updatedAt: null }

describe('settings tabs', () => {
  it('restores keyboard focus after closing the provider dialog', async () => {
    vi.spyOn(api,'modelConfiguration').mockResolvedValue(empty)
    mount('/settings?tab=models')
    const button=await screen.findByRole('button',{name:'添加供应商'})
    await waitFor(()=>expect(button).toBeEnabled())
    const user=userEvent.setup()
    await user.click(button)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(()=>expect(button).toHaveFocus())
  })
  it('keeps the session visible when logout fails and permits retry', async () => {
    vi.spyOn(api, 'authState').mockResolvedValueOnce({ authEnabled: true, authenticated: true, setupRequired: false, user: { id: 'admin', username: 'admin', displayName: 'Admin', role: 'administrator' } }).mockResolvedValue({authEnabled:true,authenticated:false,setupRequired:false,user:null})
    const logout = vi.spyOn(api, 'logout').mockRejectedValueOnce(new Error('offline')).mockResolvedValue({authenticated:false})
    mount('/settings', true)
    await userEvent.setup().click(await screen.findByRole('button', { name: '退出登录' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.getByText('Admin')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '退出登录' }))
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('heading', {name:'登录'})).toBeInTheDocument()
  })
  it('separates system and model requests and supports URL history', async () => {
    const models = vi.spyOn(api, 'modelConfiguration').mockResolvedValue(empty)
    mount()
    expect(screen.getByRole('tab', { name: '系统设置' })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByRole('region', { name: '用户列表' })).toBeInTheDocument()
    expect(models).not.toHaveBeenCalled()
    await userEvent.setup().click(screen.getByRole('tab', { name: '模型设置' }))
    await waitFor(() => expect(models).toHaveBeenCalledTimes(1))
    expect(screen.getByLabelText('route')).toHaveTextContent('?tab=models')
    expect(screen.queryByRole('region', { name: '用户列表' })).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'History back' }))
    expect(screen.getByRole('tab', { name: '系统设置' })).toHaveAttribute('aria-selected', 'true')
  })

  it('opens models directly, disables editing while failed and retries without a false empty state', async () => {
    vi.spyOn(api, 'modelConfiguration').mockRejectedValueOnce(new Error('offline')).mockResolvedValue(empty)
    mount('/settings?tab=models')
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(api.platformSettings).not.toHaveBeenCalled()
    expect(api.users).not.toHaveBeenCalled()
    expect(document.querySelector('.settings-empty')).toBeNull()
    expect(screen.getByRole('button', { name: '添加供应商' })).toBeDisabled()
    await userEvent.setup().click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '添加供应商' })).toBeEnabled())
  })

  it('keeps model settings read-only for non-administrators', async () => {
    vi.spyOn(api, 'authState').mockResolvedValue({ authEnabled: true, authenticated: true, setupRequired: false, user: { id: 'viewer', username: 'viewer', displayName: 'Viewer', role: 'viewer' } })
    vi.spyOn(api, 'modelConfiguration').mockResolvedValue(empty)
    const update = vi.spyOn(api, 'updateModelConfiguration')
    mount('/settings?tab=models', true)
    expect(await screen.findByText('仅管理员可修改模型配置')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '添加供应商' })).toBeDisabled()
    expect(update).not.toHaveBeenCalled()
  })
})
