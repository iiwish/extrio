import { describe, expect, it } from 'vitest'
import { legacyExperienceTarget } from './legacy-experience'

describe('legacy experience links', () => {
  it.each([
    ['#/settings?tab=models', '/settings'],
    ['#/overview', '/'],
    ['#/collections/setup?step=fields', '/collections'],
    ['#/collectors?step=fields', '/collections'],
    ['#/collectors/review?source=province', '/collectors'],
    ['#/items?source=city&state=error', '/items'],
    ['#/runs', '/runs'],
    ['', '/collections'],
    ['#https://example.com', '/collections'],
  ])('maps %s to the live application without synthetic state', (hash, target) => {
    expect(legacyExperienceTarget(hash)).toBe(target)
  })
})
