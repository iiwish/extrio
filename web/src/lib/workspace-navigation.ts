import { useLocation, useSearchParams } from 'react-router-dom'

function safeWorkspacePath(value: string | null): value is string {
  return Boolean(value && !value.includes('\\') && !/[\r\n]/.test(value)
    && /^\/(?:collections|collectors|runs|ai-runs|items)(?:[/?#]|$)/.test(value))
}

export function returnTarget(params: URLSearchParams, fallback: string) {
  const value = params.get('returnTo')
  return safeWorkspacePath(value) ? value : fallback
}

export function withReturnTo(target: string, from: string) {
  if (!safeWorkspacePath(from)) return target
  const url = new URL(target, 'http://workspace.local')
  url.searchParams.set('returnTo', from)
  return `${url.pathname}${url.search}${url.hash}`
}

export function useWorkspaceLink() {
  const { pathname, search } = useLocation()
  return (target: string) => withReturnTo(target, `${pathname}${search}`)
}

export function useWorkspaceSection<T extends string>(sections: readonly T[], fallback: T) {
  const [params, setParams] = useSearchParams()
  const requested = params.get('section') as T
  const value = sections.includes(requested) ? requested : fallback
  return [value, (next: string) => {
    const updated = new URLSearchParams(params)
    updated.set('section', next)
    setParams(updated, { replace: true })
  }] as const
}
