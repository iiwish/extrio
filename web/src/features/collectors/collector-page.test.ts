import { describe, expect, it } from 'vitest'
import { defaultCollectorTab } from './collector-page'

describe('collector workspace defaults', () => {
  it('opens the task that matches the collector lifecycle state', () => {
    expect(defaultCollectorTab('ready_review')).toBe('rule')
    expect(defaultCollectorTab('published')).toBe('overview')
    expect(defaultCollectorTab('draft')).toBe('overview')
    expect(defaultCollectorTab('exploring')).toBe('overview')
  })
})
