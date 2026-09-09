import { Navigate, useLocation } from 'react-router-dom'

export function legacyExperienceTarget(hash: string): string {
  const path = hash.replace(/^#/, '').split('?')[0]
  if (path === '/overview') return '/'
  if (path === '/settings' || path === '/runs' || path === '/items') return path
  if (path === '/collectors' && !hash.includes('step=')) return '/collectors'
  if (path.startsWith('/collectors/review')) return '/collectors'
  return '/collections'
}

export function LegacyExperienceRedirect() {
  const { hash } = useLocation()
  return <Navigate replace to={legacyExperienceTarget(hash)} />
}
