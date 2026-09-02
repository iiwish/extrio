import i18next from 'i18next'
import type { CollectorStatus } from '@/api/types'

export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

const statusKeys = [
  'draft',
  'exploring',
  'ready_review',
  'published',
  'queued',
  'running',
  'finalizing',
  'succeeded',
  'partially_succeeded',
  'failed',
  'cancelled',
  'timed_out',
  'accepted',
  'rejected',
] as const

export type StatusKey = (typeof statusKeys)[number]

export function statusLabel(status: StatusKey) {
  return i18next.t(`common:status.${status}`)
}

export function statusTone(status: StatusKey): StatusTone {
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
