import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import type { AuthState } from '@/api/types'
import { AuthGate } from './auth-gate'

const unauthenticated: AuthState = {
  authEnabled: true,
  setupRequired: true,
  authenticated: false,
  user: null,
}

const authenticated: AuthState = {
  authEnabled: true,
  setupRequired: false,
  authenticated: true,
  user: { id: 'user_admin', username: 'admin', displayName: 'Operator', role: 'administrator' },
}

describe('AuthGate', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('finishes first-run administrator setup before rendering the workspace', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'authState').mockResolvedValue(unauthenticated)
    const setup = vi.spyOn(api, 'setupAuth').mockResolvedValue(authenticated)

    render(<AuthGate><div>采集工作台</div></AuthGate>)

    expect(await screen.findByRole('heading', { name: '创建管理员' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('显示名称'), 'Operator')
    await user.type(screen.getByLabelText('用户名'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'correct-horse-battery-staple')
    await user.click(screen.getByRole('button', { name: '完成设置' }))

    expect(setup).toHaveBeenCalledWith({
      username: 'admin',
      displayName: 'Operator',
      password: 'correct-horse-battery-staple',
    })
    expect(await screen.findByText('采集工作台')).toBeInTheDocument()
  })

  it('renders the workspace immediately for an authenticated session', async () => {
    vi.spyOn(api, 'authState').mockResolvedValue(authenticated)
    render(<AuthGate><div>采集工作台</div></AuthGate>)
    expect(await screen.findByText('采集工作台')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '登录' })).not.toBeInTheDocument()
  })
})
