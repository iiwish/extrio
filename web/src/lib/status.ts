import type { CollectorStatus, ItemDecision, RunStatus } from '@/api/types'

export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

const labels: Record<CollectorStatus | RunStatus | ItemDecision, string> = {
  draft: '待探索',
  exploring: '探索中',
  ready_review: '待审核',
  published: '已发布',
  queued: '排队中',
  running: '采集中',
  finalizing: '终结中',
  succeeded: '已成功',
  partially_succeeded: '部分成功',
  failed: '失败',
  cancelled: '已取消',
  timed_out: '已超时',
  accepted: '已接收',
  rejected: '已拒绝',
}

export function statusLabel(status: keyof typeof labels) {
  return labels[status]
}

export function statusTone(status: keyof typeof labels): StatusTone {
  if (['published', 'succeeded', 'accepted'].includes(status)) return 'success'
  if (['ready_review', 'partially_succeeded'].includes(status)) return 'warning'
  if (['failed', 'rejected', 'timed_out'].includes(status)) return 'danger'
  if (['queued', 'running', 'finalizing', 'exploring'].includes(status)) return 'info'
  return 'neutral'
}

export function collectorStage(status: CollectorStatus, hasRun: boolean) {
  if (hasRun) return 4
  if (status === 'published') return 3
  if (status === 'ready_review') return 2
  if (status === 'exploring') return 1
  return 0
}
