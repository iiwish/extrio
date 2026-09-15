import { describe, expect, it } from 'vitest'
import { seedCollectors, seedRuns } from '@/api/fixtures'
import { collectorAttention } from './collector-attention'

const source = { ...seedCollectors[0], lifecycle: 'active' as const, status: 'published' as const, activeRuleVersion: 'rule', activeOperationId: null, latestRunId: null, pendingCollectionVersion: null }
const run = { ...seedRuns[0], status: 'succeeded' as const, rejectedCount: 0 }

describe('shared current-source attention', () => {
  it('includes a published source awaiting its first run', () => {
    expect(collectorAttention(source)?.reason).toBe('firstRun')
  })
  it('does not use an unrelated historical run as the latest result', () => {
    expect(collectorAttention({ ...source, latestRunId: 'missing' }, run)?.reason).toBe('inspectRun')
  })
  it('excludes archived sources and active execution from pending work', () => {
    expect(collectorAttention({ ...source, lifecycle: 'archived' })).toBeNull()
    expect(collectorAttention({ ...source, activeOperationId: 'op' })).toBeNull()
  })
  it.each(['queued', 'running', 'finalizing'] as const)('does not classify partial counters of a %s run as a completed problem', status => {
    expect(collectorAttention({ ...source, latestRunId: run.id }, { ...run, status, rejectedCount: 3 })).toBeNull()
  })
  it.each(['failed', 'cancelled', 'timed_out'] as const)('includes the latest %s run', status => {
    expect(collectorAttention({ ...source, latestRunId: run.id }, { ...run, status })?.reason).toBe('fixFailedRun')
  })
  it('separates missing rule, migration, partial results and quality rejections', () => {
    expect(collectorAttention({ ...source, activeRuleVersion: null })?.reason).toBe('checkPublish')
    expect(collectorAttention({ ...source, pendingCollectionVersion: 'v2' })?.reason).toBe('migration')
    expect(collectorAttention({ ...source, latestRunId: run.id }, { ...run, status: 'partially_succeeded' })?.reason).toBe('partialRun')
    expect(collectorAttention({ ...source, latestRunId: run.id }, { ...run, rejectedCount: 1 })?.reason).toBe('checkRejected')
    expect(collectorAttention({ ...source, latestRunId: run.id }, run)).toBeNull()
  })
})
