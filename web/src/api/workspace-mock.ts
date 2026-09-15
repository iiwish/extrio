import type { AiRun, Collection, CollectorDetail, Run } from './types'
import { collectorAttention } from '@/features/collectors/collector-attention'

export function mockNumberedPage<T>(params: URLSearchParams, values: T[], counts: Record<string, number>) {
  const pageSize = Math.min(200, Math.max(1, Number(params.get('limit') ?? 50)))
  const totalPages = Math.max(1, Math.ceil(values.length / pageSize))
  const page = Math.min(totalPages, Math.max(1, Number(params.get('page') ?? 1)))
  return { items: values.slice((page - 1) * pageSize, page * pageSize), total: values.length,
    pagination: { page, pageSize, total: values.length, totalPages }, counts, page: { nextCursor: null } }
}

export function mockCollectionPage(params: URLSearchParams, rows: Collection[]) {
  const status = params.get('status') ?? 'active'
  const term = (params.get('q') ?? '').trim().toLowerCase()
  const values = rows.filter(row => (status === 'all' || row.status === status) && `${row.name} ${row.intent}`.toLowerCase().includes(term))
    .sort((a, b) => a.id.localeCompare(b.id)).sort((a, b) => (Date.parse(a.updatedAt) - Date.parse(b.updatedAt)) * (params.get('sort') === 'updated_asc' ? 1 : -1))
  return mockNumberedPage(params, values, { all: rows.length, active: rows.filter(row => row.status === 'active').length, archived: rows.filter(row => row.status === 'archived').length })
}

export function mockCollectorPage(params: URLSearchParams, rows: CollectorDetail[], runs: Run[]) {
  const scope = rows.filter(row => params.get('lifecycle') === 'all' || (row.lifecycle ?? 'active') === (params.get('lifecycle') ?? 'active'))
  const runMap = new Map(runs.map(run => [run.id, run]))
  const attention = (row: CollectorDetail) => Boolean(collectorAttention(row, runMap.get(row.latestRunId ?? '')))
  const view = params.get('view') ?? 'all'
  const term = (params.get('q') ?? '').trim().toLowerCase()
  const values = scope.filter(row => (!params.get('collectionId') || row.collectionId === params.get('collectionId'))
    && (view === 'all' || (view === 'attention' ? attention(row) : row.status === 'published'))
    && `${row.name} ${row.sourceUrl} ${row.collectionName}`.toLowerCase().includes(term))
  const result = mockNumberedPage(params, values, { all: scope.length, attention: scope.filter(attention).length, published: scope.filter(row => row.status === 'published').length })
  return { ...result, latestRuns: runs.filter(run => result.items.some(row => row.latestRunId === run.id)),
    collections: [...new Map(scope.map(row => [row.collectionId, { id: row.collectionId, name: row.collectionName, version: row.collectionVersion }])).values()] }
}

export function mockRunPage(params: URLSearchParams, rows: Run[]) {
  const status = params.get('status') ?? 'all'
  const term = (params.get('q') ?? '').trim().toLowerCase()
  const attention = (row: Run) => ['partially_succeeded', 'failed', 'timed_out'].includes(row.status)
  return mockNumberedPage(params, rows.filter(row => (status === 'all' || (status === 'attention' ? attention(row) : row.status === 'succeeded'))
    && `${row.collectorName} ${row.id}`.toLowerCase().includes(term)),
  { all: rows.length, attention: rows.filter(attention).length, succeeded: rows.filter(row => row.status === 'succeeded').length })
}

export function mockAiRunPage(params: URLSearchParams, rows: AiRun[]) {
  const scope = rows.filter(row => !params.get('collectorId') || row.collectorId === params.get('collectorId'))
  const status = params.get('status') ?? 'all'
  const term = (params.get('q') ?? '').trim().toLowerCase()
  const groups: Record<string, (row: AiRun) => boolean> = { all: () => true, running: row => ['queued', 'running', 'finalizing'].includes(row.status),
    attention: row => row.status === 'failed' || row.resultStatus === 'no_candidate', review: row => !row.collectorDeleted && row.reviewStatus === 'ready_review' }
  return mockNumberedPage(params, scope.filter(row => groups[status](row) && `${row.collectorName} ${row.sourceUrl}`.toLowerCase().includes(term)),
    Object.fromEntries(Object.entries(groups).map(([key, match]) => [key, scope.filter(match).length])))
}
