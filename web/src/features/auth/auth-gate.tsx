import { AlertCircle, LoaderCircle, LockKeyhole } from 'lucide-react'
import { createContext, type FormEvent, type ReactNode, useCallback, useContext, useEffect, useState } from 'react'
import { api, ApiRequestError } from '@/api/client'
import type { AuthState, AuthUser } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface AuthContextValue {
  user: AuthUser
  logout: () => Promise<void>
}

const developmentUser: AuthUser = {
  id: 'user_local_development',
  username: 'local',
  displayName: 'Local Administrator',
  role: 'administrator',
}

const AuthContext = createContext<AuthContextValue>({ user: developmentUser, logout: async () => {} })

export function useAuth() {
  return useContext(AuthContext)
}

function AuthForm({ state, onAuthenticated }: { state: AuthState; onAuthenticated: (state: AuthState) => void }) {
  const setup = state.setupRequired
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    const form = new FormData(event.currentTarget)
    const username = String(form.get('username') ?? '')
    const password = String(form.get('password') ?? '')
    try {
      const next = setup
        ? await api.setupAuth({ username, password, displayName: String(form.get('displayName') ?? '') || undefined })
        : await api.login({ username, password })
      onAuthenticated(next)
    } catch (reason) {
      setError(reason instanceof ApiRequestError ? reason.message : '操作失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-screen">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand"><span className="brand-mark">E</span><strong>Extrio</strong></div>
        <div className="auth-heading">
          <LockKeyhole aria-hidden="true" />
          <div><h1 id="auth-title">{setup ? '创建管理员' : '登录'}</h1><p>{setup ? '完成此实例的首次设置' : '进入采集运营控制台'}</p></div>
        </div>
        <form className="auth-form" onSubmit={submit}>
          {setup && <label><span>显示名称</span><Input name="displayName" autoComplete="name" maxLength={64} placeholder="管理员" /></label>}
          <label><span>用户名</span><Input name="username" autoComplete="username" minLength={3} maxLength={64} required autoFocus /></label>
          <label><span>密码</span><Input name="password" type="password" autoComplete={setup ? 'new-password' : 'current-password'} minLength={setup ? 8 : undefined} maxLength={256} required /></label>
          {error && <div className="auth-error" role="alert"><AlertCircle />{error}</div>}
          <Button type="submit" size="lg" disabled={submitting}>
            {submitting && <LoaderCircle className="animate-spin" />}{setup ? '完成设置' : '登录'}
          </Button>
        </form>
      </section>
    </main>
  )
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const loadState = useCallback(async () => {
    try {
      setState(await api.authState())
      setLoadError(null)
    } catch (reason) {
      setLoadError(reason instanceof ApiRequestError ? reason.message : '无法连接控制面')
    }
  }, [])

  useEffect(() => {
    const initialLoad = window.setTimeout(loadState, 0)
    window.addEventListener('extrio:auth-required', loadState)
    return () => {
      window.clearTimeout(initialLoad)
      window.removeEventListener('extrio:auth-required', loadState)
    }
  }, [loadState])

  if (loadError) {
    return <main className="auth-screen"><section className="auth-panel auth-unavailable"><AlertCircle /><h1>控制面不可用</h1><p>{loadError}</p><Button variant="outline" onClick={loadState}>重试</Button></section></main>
  }
  if (!state) {
    return <main className="auth-screen" aria-label="正在连接控制面"><LoaderCircle className="auth-loader animate-spin" /></main>
  }
  if (!state.authenticated || !state.user) {
    return <AuthForm state={state} onAuthenticated={setState} />
  }

  async function logout() {
    await api.logout()
    await loadState()
  }

  return <AuthContext.Provider value={{ user: state.user, logout }}>{children}</AuthContext.Provider>
}
