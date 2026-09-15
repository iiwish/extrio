import type { CollectorDetail, Run } from '@/api/types'

export const attentionRunStatuses = new Set(['partially_succeeded', 'failed', 'cancelled', 'timed_out'])
export const activeRunStatuses = new Set(['queued', 'running', 'finalizing'])

const priorities = {
  fixFailedRun: 0, partialRun: 1, migration: 2, checkPublish: 3,
  reviewRule: 4, generateRule: 5, exploreProgress: 6, inspectRun: 7,
  firstRun: 8, checkRejected: 9,
} as const

export function collectorAttention(collector: CollectorDetail, run?: Run) {
  if (collector.lifecycle === 'archived') return null
  const latestRun = run?.id === collector.latestRunId ? run : undefined
  // In-flight counters and older run failures are not current completed work.
  if (collector.activeOperationId || (latestRun && activeRunStatuses.has(latestRun.status))) return null
  const reason = latestRun && ['failed', 'cancelled', 'timed_out'].includes(latestRun.status) ? 'fixFailedRun'
    : latestRun?.status === 'partially_succeeded' ? 'partialRun'
    : collector.pendingCollectionVersion ? 'migration'
    : collector.status === 'ready_review' ? 'reviewRule'
    : collector.status === 'draft' ? 'generateRule'
    : collector.status === 'exploring' ? 'exploreProgress'
    : !collector.activeRuleVersion ? 'checkPublish'
    : collector.latestRunId && !latestRun ? 'inspectRun'
    : !collector.latestRunId ? 'firstRun'
    : latestRun && latestRun.rejectedCount > 0 ? 'checkRejected' : null
  return reason ? { reason, rank: priorities[reason] } : null
}
