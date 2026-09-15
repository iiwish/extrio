import { describe, expect, it } from 'vitest'
import { returnTarget, withReturnTo } from './workspace-navigation'

describe('workspace return context', () => {
  it('preserves filters and the exact section through a refreshable URL', () => {
    const target = withReturnTo('/collectors/source?section=rules', '/collections/req?q=全国&status=all&section=sources')
    const params = new URL(target, 'http://localhost').searchParams
    expect(params.get('section')).toBe('rules')
    expect(returnTarget(params, '/collectors')).toBe('/collections/req?q=全国&status=all&section=sources')
  })
  it('rejects external, protocol-relative and unsupported return targets', () => {
    for (const target of ['https://evil.example', '//evil.example', '/\\evil.example', '/api/v1/auth/logout', '/collectors-other']) {
      expect(returnTarget(new URLSearchParams({ returnTo: target }), '/runs')).toBe('/runs')
    }
  })
})
