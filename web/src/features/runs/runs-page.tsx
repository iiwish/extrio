import { useQuery } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { ArrowRight, Bot, Clock3, PlayCircle, RefreshCw, Search, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { AiRun, Run } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { collectorDisplayName } from '@/features/collectors/collector-presentation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const attentionStatuses = ['partially_succeeded', 'failed', 'timed_out']

export function RunsPage() {
  const { t } = useTranslation('runs')
  const [searchParams, setSearchParams] = useSearchParams()
  const view = searchParams.get('view') === 'ai' ? 'ai' : 'collection'
  const filter = searchParams.get('status') ?? 'all'
  const search = searchParams.get('q') ?? ''
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: api.runs, enabled: view === 'collection' })
  const aiRunsQuery = useQuery({ queryKey: ['ai-runs'], queryFn: () => api.aiRuns(), enabled: view === 'ai' })

  function updateParam(key: 'view' | 'status' | 'q', value: string, emptyValue: string) {
    const next = new URLSearchParams(searchParams)
    if (!value || value === emptyValue) next.delete(key)
    else next.set(key, value)
    if (key === 'view') next.delete('status')
    setSearchParams(next)
  }

  return (
    <div className="page-frame entity-page runs-page">
      <h1 className="sr-only">{t('title')}</h1>
      <Tabs value={view} onValueChange={(value) => updateParam('view', value, 'collection')} className="runs-view-tabs">
        <div className="run-workspace-nav runs-view-nav">
          <TabsList variant="line" aria-label={t('tabs.viewAria')}>
            <TabsTrigger value="collection"><PlayCircle />{t('tabs.collection')}</TabsTrigger>
            <TabsTrigger value="ai"><Sparkles />{t('tabs.ai')}</TabsTrigger>
          </TabsList>
        </div>
      </Tabs>

      {view === 'collection'
        ? <CollectionRunsView query={runsQuery} filter={filter} search={search} updateParam={updateParam} />
        : <AiRunsView query={aiRunsQuery} filter={filter} search={search} updateParam={updateParam} />}
    </div>
  )
}

type RunsQuery = ReturnType<typeof useQuery<Run[]>>
type AiRunsQuery = ReturnType<typeof useQuery<AiRun[]>>
type UpdateParam = (key: 'view' | 'status' | 'q', value: string, emptyValue: string) => void

function CollectionRunsView({ query, filter, search, updateParam }: { query: RunsQuery; filter: string; search: string; updateParam: UpdateParam }) {
  const { t } = useTranslation('runs')
  const runs = query.data ?? []
  const normalizedSearch = search.trim().toLowerCase()
  const filtered = runs.filter((run) => {
    const matchesStatus = filter === 'all' || (filter === 'attention' ? attentionStatuses.includes(run.status) : run.status === 'succeeded')
    const matchesSearch = !normalizedSearch || `${run.collectorName} ${run.id}`.toLowerCase().includes(normalizedSearch)
    return matchesStatus && matchesSearch
  })
  const attentionCount = runs.filter((run) => attentionStatuses.includes(run.status)).length

  return <>
    <div className="filter-card runs-toolbar" aria-label={t('toolbar.aria')}>
      <div className="segmented" role="group" aria-label={t('toolbar.filterAria')}>
        <Button variant={filter === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'all', 'all')}>{t('filter.all')} <span>{runs.length}</span></Button>
        <Button variant={filter === 'attention' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'attention', 'all')}>{t('filter.attention')} <span>{attentionCount}</span></Button>
        <Button variant={filter === 'succeeded' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'succeeded', 'all')}>{t('filter.succeeded')} <span>{runs.filter((run) => run.status === 'succeeded').length}</span></Button>
      </div>
      <RunToolbarActions search={search} onSearch={(value) => updateParam('q', value, '')} onRefresh={() => query.refetch()} label={t('toolbar.searchLabel')} placeholder={t('toolbar.searchPlaceholder')} />
    </div>

    <section className="object-list run-object-list" aria-label={t('list.aria')}>
      <div className="object-list-head run-grid" aria-hidden="true">
        <span>{t('list.colRun')}</span><span>{t('list.colStatus')}</span><span>{t('list.colAccepted')}</span><span>{t('list.colRejected')}</span><span>{t('list.colScope')}</span><span>{t('list.colTime')}</span><span />
      </div>
      {query.isLoading && Array.from({ length: 6 }, (_, index) => <Skeleton className="run-list-skeleton" key={index} />)}
      {filtered.map((run) => <RunRow run={run} key={run.id} />)}
      {!query.isLoading && filtered.length === 0 && <div className="card-empty run-list-empty">{t('list.empty')}</div>}
    </section>
  </>
}

function AiRunsView({ query, filter, search, updateParam }: { query: AiRunsQuery; filter: string; search: string; updateParam: UpdateParam }) {
  const { t } = useTranslation('runs')
  const runs = query.data ?? []
  const normalizedSearch = search.trim().toLowerCase()
  const isAttention = (run: AiRun) => run.status === 'failed' || run.resultStatus === 'no_candidate'
  const filtered = runs.filter((run) => {
    const matchesStatus = filter === 'all'
      || (filter === 'running' && ['queued', 'running', 'finalizing'].includes(run.status))
      || (filter === 'attention' && isAttention(run))
      || (filter === 'review' && run.reviewStatus === 'ready_review')
    const matchesSearch = !normalizedSearch || `${run.collectorName} ${run.sourceUrl}`.toLowerCase().includes(normalizedSearch)
    return matchesStatus && matchesSearch
  })

  return <>
    <div className="filter-card runs-toolbar" aria-label={t('toolbar.aiAria')}>
      <div className="segmented" role="group" aria-label={t('toolbar.aiFilterAria')}>
        <Button variant={filter === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'all', 'all')}>{t('filter.all')} <span>{runs.length}</span></Button>
        <Button variant={filter === 'running' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'running', 'all')}>{t('filter.running')} <span>{runs.filter((run) => ['queued', 'running', 'finalizing'].includes(run.status)).length}</span></Button>
        <Button variant={filter === 'review' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'review', 'all')}>{t('filter.review')} <span>{runs.filter((run) => run.reviewStatus === 'ready_review').length}</span></Button>
        <Button variant={filter === 'attention' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'attention', 'all')}>{t('filter.attention')} <span>{runs.filter(isAttention).length}</span></Button>
      </div>
      <RunToolbarActions search={search} onSearch={(value) => updateParam('q', value, '')} onRefresh={() => query.refetch()} label={t('toolbar.aiSearchLabel')} placeholder={t('toolbar.aiSearchPlaceholder')} />
    </div>

    <section className="object-list run-object-list ai-run-object-list" aria-label={t('aiList.aria')}>
      <div className="object-list-head ai-run-grid" aria-hidden="true">
        <span>{t('aiList.colCollector')}</span><span>{t('aiList.colTask')}</span><span>{t('aiList.colStatus')}</span><span>{t('aiList.colResult')}</span><span>{t('aiList.colModelUsage')}</span><span>{t('aiList.colTime')}</span><span />
      </div>
      {query.isLoading && Array.from({ length: 5 }, (_, index) => <Skeleton className="run-list-skeleton" key={index} />)}
      {filtered.map((run) => <AiRunRow run={run} key={run.id} />)}
      {!query.isLoading && filtered.length === 0 && <div className="card-empty run-list-empty">{t('aiList.empty')}</div>}
    </section>
  </>
}

function RunToolbarActions({ search, onSearch, onRefresh, label, placeholder }: { search: string; onSearch: (value: string) => void; onRefresh: () => void; label: string; placeholder: string }) {
  const { t } = useTranslation('runs')
  return <div className="runs-toolbar-actions">
    <div className="toolbar-search runs-search"><Search /><Input value={search} onChange={(event) => onSearch(event.target.value)} placeholder={placeholder} aria-label={label} /></div>
    <span className="filter-context"><Clock3 />{t('toolbar.sortHint')}</span>
    <Button variant="outline" size="icon-sm" aria-label={t('common:action.refresh')} onClick={onRefresh}><RefreshCw /></Button>
  </div>
}

function RunRow({ run }: { run: Run }) {
  const { t } = useTranslation('runs')
  const failed = ['failed', 'timed_out', 'cancelled'].includes(run.status)
  return (
    <Link className={`object-row run-grid run-list-row ${failed ? 'has-error' : ''}`} to={`/runs/${run.id}`}>
      <span className="object-primary"><span className="source-icon"><PlayCircle /></span><span><strong>{collectorDisplayName(run.collectorName)}</strong><small>{run.id}</small></span></span>
      <StatusBadge status={run.status} />
      <span className="run-metric-cell"><strong>{run.acceptedCount}</strong><small>{t('row.acceptedUnit')}</small></span>
      <span className={`run-metric-cell ${run.rejectedCount > 0 ? 'danger' : ''}`}><strong>{run.rejectedCount}</strong><small>{t('row.rejectedUnit')}</small></span>
      <span className="run-scope-cell">
        <span><Badge variant="outline">{run.executionMode === 'incremental' ? t('mode.incremental') : run.executionMode === 'initial' ? t('mode.initial') : t('mode.historical')}</Badge><strong>{run.collectionMode === 'list_detail' ? t('row.listAndDetailPages', { list: run.listPagesFetched, fetched: run.detailPagesFetched, discovered: run.detailUrlsDiscovered }) : t('row.listPages', { count: run.listPagesFetched })}</strong></span>
        <small>{t('row.changeSummary', { count: run.newItems + run.updatedItems, reason: stopReasonLabel(t, run.paginationStopReason) })}</small>
      </span>
      <span className="run-time-cell"><strong>{run.startedAt}</strong><small>{run.duration}</small></span>
      <ArrowRight className="row-arrow" />
    </Link>
  )
}

function AiRunRow({ run }: { run: AiRun }) {
  const { t } = useTranslation('runs')
  const failed = run.status === 'failed'
  return <Link className={`object-row ai-run-grid run-list-row ${failed ? 'has-error' : ''}`} to={`/ai-runs/${run.id}`}>
    <span className="object-primary"><span className="source-icon ai"><Bot /></span><span><strong>{collectorDisplayName(run.collectorName)}</strong><small>{sourcePath(run.sourceUrl)}</small></span></span>
    <span className="ai-run-kind"><strong>{run.kind === 'rule_repair' ? t('aiRow.kindRuleRepair') : t('aiRow.kindRuleGeneration')}</strong><small>{triggerLabel(t, run.trigger)}</small></span>
    <AiStatusBadge run={run} />
    <span className="ai-run-result"><strong>{resultLabel(t, run)}</strong><small>{phaseLabel(t, run.phase)} · {run.progress}%</small></span>
    <span className="run-metric-cell"><strong>{formatTokens(run.modelSummary.totalTokens)}</strong><small>{t('aiRow.invocations', { count: run.modelSummary.invocationCount })}</small></span>
    <span className="run-time-cell"><strong>{formatDateTime(run.createdAt)}</strong><small>{formatDuration(t, run.durationMs)}</small></span>
    <ArrowRight className="row-arrow" />
  </Link>
}

function AiStatusBadge({ run }: { run: AiRun }) {
  const { t } = useTranslation('runs')
  const active = ['queued', 'running', 'finalizing'].includes(run.status)
  const tone = run.status === 'failed' ? 'danger' : run.reviewStatus === 'ready_review' ? 'review' : active ? 'running' : 'success'
  const label = run.status === 'failed' ? t('aiStatus.failed') : run.reviewStatus === 'ready_review' ? t('aiStatus.readyReview') : active ? t('aiStatus.running') : run.reviewStatus === 'published' ? t('aiStatus.published') : t('aiStatus.completed')
  return <Badge variant="outline" className={`ai-status-badge ${tone}`}><span />{label}</Badge>
}

function resultLabel(t: TFunction, run: AiRun) {
  if (run.resultStatus === 'candidate_ready') return t('result.candidate_ready')
  if (run.resultStatus === 'no_candidate') return t('result.no_candidate')
  return t('result.pending')
}

function triggerLabel(t: TFunction, trigger: AiRun['trigger']) {
  return { initial_generation: t('trigger.initial_generation'), regeneration: t('trigger.regeneration'), repair: t('trigger.repair') }[trigger]
}

function phaseLabel(t: TFunction, phase: AiRun['phase']) {
  return { queued: t('phase.queued'), fetching_list: t('phase.fetching_list'), discovering_details: t('phase.discovering_details'), fetching_details: t('phase.fetching_details'), validating: t('phase.validating'), finalizing: t('phase.finalizing'), completed: t('phase.completed') }[phase]
}

function sourcePath(raw: string) {
  try {
    const url = new URL(raw)
    return `${url.host}${url.pathname === '/' ? '' : url.pathname}`
  } catch {
    return raw
  }
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
}

function formatDuration(t: TFunction, value: number | null) {
  if (value === null) return t('duration.running')
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`
}

function formatTokens(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}

function stopReasonLabel(t: TFunction, reason: Run['paginationStopReason']) {
  return {
    not_applicable: t('stopReason.not_applicable'), empty_page: t('stopReason.empty_page'), next_link_exhausted: t('stopReason.next_link_exhausted'), max_pages: t('stopReason.max_pages'), max_items: t('stopReason.max_items'), budget_exhausted: t('stopReason.budget_exhausted'), cross_host_blocked: t('stopReason.cross_host_blocked'), time_window_reached: t('stopReason.time_window_reached'), checkpoint_reached: t('stopReason.checkpoint_reached'), detail_fetch_incomplete: t('stopReason.detail_fetch_incomplete'),
  }[reason]
}
