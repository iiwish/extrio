import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Bot, Clock3, PlayCircle, RefreshCw, Search, Sparkles } from 'lucide-react'
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
      <h1 className="sr-only">运行</h1>
      <Tabs value={view} onValueChange={(value) => updateParam('view', value, 'collection')} className="runs-view-tabs">
        <div className="run-workspace-nav runs-view-nav">
          <TabsList variant="line" aria-label="运行类型">
            <TabsTrigger value="collection"><PlayCircle />采集运行</TabsTrigger>
            <TabsTrigger value="ai"><Sparkles />AI 任务</TabsTrigger>
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
  const runs = query.data ?? []
  const normalizedSearch = search.trim().toLowerCase()
  const filtered = runs.filter((run) => {
    const matchesStatus = filter === 'all' || (filter === 'attention' ? attentionStatuses.includes(run.status) : run.status === 'succeeded')
    const matchesSearch = !normalizedSearch || `${run.collectorName} ${run.id}`.toLowerCase().includes(normalizedSearch)
    return matchesStatus && matchesSearch
  })
  const attentionCount = runs.filter((run) => attentionStatuses.includes(run.status)).length

  return <>
    <div className="filter-card runs-toolbar" aria-label="运行工具栏">
      <div className="segmented" role="group" aria-label="Run 状态筛选">
        <Button variant={filter === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'all', 'all')}>全部 <span>{runs.length}</span></Button>
        <Button variant={filter === 'attention' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'attention', 'all')}>需处理 <span>{attentionCount}</span></Button>
        <Button variant={filter === 'succeeded' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'succeeded', 'all')}>完整成功 <span>{runs.filter((run) => run.status === 'succeeded').length}</span></Button>
      </div>
      <RunToolbarActions search={search} onSearch={(value) => updateParam('q', value, '')} onRefresh={() => query.refetch()} label="搜索运行" placeholder="搜索采集器名称或 Run ID" />
    </div>

    <section className="object-list run-object-list" aria-label="Run 列表">
      <div className="object-list-head run-grid" aria-hidden="true">
        <span>运行</span><span>终态</span><span>接收</span><span>拒绝</span><span>范围与停止</span><span>开始 / 耗时</span><span />
      </div>
      {query.isLoading && Array.from({ length: 6 }, (_, index) => <Skeleton className="run-list-skeleton" key={index} />)}
      {filtered.map((run) => <RunRow run={run} key={run.id} />)}
      {!query.isLoading && filtered.length === 0 && <div className="card-empty run-list-empty">没有符合当前筛选和搜索的运行。</div>}
    </section>
  </>
}

function AiRunsView({ query, filter, search, updateParam }: { query: AiRunsQuery; filter: string; search: string; updateParam: UpdateParam }) {
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
    <div className="filter-card runs-toolbar" aria-label="AI 任务工具栏">
      <div className="segmented" role="group" aria-label="AI 任务状态筛选">
        <Button variant={filter === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'all', 'all')}>全部 <span>{runs.length}</span></Button>
        <Button variant={filter === 'running' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'running', 'all')}>进行中 <span>{runs.filter((run) => ['queued', 'running', 'finalizing'].includes(run.status)).length}</span></Button>
        <Button variant={filter === 'review' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'review', 'all')}>待审核 <span>{runs.filter((run) => run.reviewStatus === 'ready_review').length}</span></Button>
        <Button variant={filter === 'attention' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'attention', 'all')}>需处理 <span>{runs.filter(isAttention).length}</span></Button>
      </div>
      <RunToolbarActions search={search} onSearch={(value) => updateParam('q', value, '')} onRefresh={() => query.refetch()} label="搜索 AI 任务" placeholder="搜索采集器或来源 URL" />
    </div>

    <section className="object-list run-object-list ai-run-object-list" aria-label="AI 任务列表">
      <div className="object-list-head ai-run-grid" aria-hidden="true">
        <span>采集器</span><span>任务</span><span>状态</span><span>结果</span><span>模型消耗</span><span>开始 / 耗时</span><span />
      </div>
      {query.isLoading && Array.from({ length: 5 }, (_, index) => <Skeleton className="run-list-skeleton" key={index} />)}
      {filtered.map((run) => <AiRunRow run={run} key={run.id} />)}
      {!query.isLoading && filtered.length === 0 && <div className="card-empty run-list-empty">没有符合当前筛选和搜索的 AI 任务。</div>}
    </section>
  </>
}

function RunToolbarActions({ search, onSearch, onRefresh, label, placeholder }: { search: string; onSearch: (value: string) => void; onRefresh: () => void; label: string; placeholder: string }) {
  return <div className="runs-toolbar-actions">
    <div className="toolbar-search runs-search"><Search /><Input value={search} onChange={(event) => onSearch(event.target.value)} placeholder={placeholder} aria-label={label} /></div>
    <span className="filter-context"><Clock3 />按开始时间倒序</span>
    <Button variant="outline" size="icon-sm" aria-label="刷新" onClick={onRefresh}><RefreshCw /></Button>
  </div>
}

function RunRow({ run }: { run: Run }) {
  const failed = ['failed', 'timed_out', 'cancelled'].includes(run.status)
  return (
    <Link className={`object-row run-grid run-list-row ${failed ? 'has-error' : ''}`} to={`/runs/${run.id}`}>
      <span className="object-primary"><span className="source-icon"><PlayCircle /></span><span><strong>{collectorDisplayName(run.collectorName)}</strong><small>{run.id}</small></span></span>
      <StatusBadge status={run.status} />
      <span className="run-metric-cell"><strong>{run.acceptedCount}</strong><small>条数据</small></span>
      <span className={`run-metric-cell ${run.rejectedCount > 0 ? 'danger' : ''}`}><strong>{run.rejectedCount}</strong><small>条候选</small></span>
      <span className="run-scope-cell">
        <span><Badge variant="outline">{run.executionMode === 'incremental' ? '增量' : run.executionMode === 'initial' ? '首次' : '历史'}</Badge><strong>{run.listPagesFetched} 列表页{run.collectionMode === 'list_detail' ? ` · ${run.detailPagesFetched}/${run.detailUrlsDiscovered} 详情页` : ''}</strong></span>
        <small>{run.newItems + run.updatedItems} 条变更 · {stopReasonLabel(run.paginationStopReason)}</small>
      </span>
      <span className="run-time-cell"><strong>{run.startedAt}</strong><small>{run.duration}</small></span>
      <ArrowRight className="row-arrow" />
    </Link>
  )
}

function AiRunRow({ run }: { run: AiRun }) {
  const failed = run.status === 'failed'
  return <Link className={`object-row ai-run-grid run-list-row ${failed ? 'has-error' : ''}`} to={`/ai-runs/${run.id}`}>
    <span className="object-primary"><span className="source-icon ai"><Bot /></span><span><strong>{collectorDisplayName(run.collectorName)}</strong><small>{sourcePath(run.sourceUrl)}</small></span></span>
    <span className="ai-run-kind"><strong>{run.kind === 'rule_repair' ? '规则修复' : '规则生成'}</strong><small>{triggerLabel(run.trigger)}</small></span>
    <AiStatusBadge run={run} />
    <span className="ai-run-result"><strong>{resultLabel(run)}</strong><small>{phaseLabel(run.phase)} · {run.progress}%</small></span>
    <span className="run-metric-cell"><strong>{formatTokens(run.modelSummary.totalTokens)}</strong><small>{run.modelSummary.invocationCount} 次调用</small></span>
    <span className="run-time-cell"><strong>{formatDateTime(run.createdAt)}</strong><small>{formatDuration(run.durationMs)}</small></span>
    <ArrowRight className="row-arrow" />
  </Link>
}

function AiStatusBadge({ run }: { run: AiRun }) {
  const tone = run.status === 'failed' ? 'danger' : run.reviewStatus === 'ready_review' ? 'review' : ['queued', 'running', 'finalizing'].includes(run.status) ? 'running' : 'success'
  const label = run.status === 'failed' ? '失败' : run.reviewStatus === 'ready_review' ? '待审核' : ['queued', 'running', 'finalizing'].includes(run.status) ? '进行中' : run.reviewStatus === 'published' ? '已发布' : '已完成'
  return <Badge variant="outline" className={`ai-status-badge ${tone}`}><span />{label}</Badge>
}

function resultLabel(run: AiRun) {
  if (run.resultStatus === 'candidate_ready') return '候选规则已生成'
  if (run.resultStatus === 'no_candidate') return '未生成候选规则'
  return '正在生成候选规则'
}

function triggerLabel(trigger: AiRun['trigger']) {
  return { initial_generation: '首次生成', regeneration: '重新生成', repair: '失败后修复' }[trigger]
}

function phaseLabel(phase: AiRun['phase']) {
  return { queued: '等待执行', fetching_list: '读取来源', discovering_details: '分析页面', fetching_details: '采集样本', validating: '验证规则', finalizing: '整理结果', completed: '已完成' }[phase]
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

function formatDuration(value: number | null) {
  if (value === null) return '执行中'
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`
}

function formatTokens(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}

function stopReasonLabel(reason: Run['paginationStopReason']) {
  return {
    not_applicable: '单页完成', empty_page: '空页停止', next_link_exhausted: '已到末页', max_pages: '达到分页上限', max_items: '达到明细上限', budget_exhausted: '请求预算耗尽', cross_host_blocked: '跨主机已阻断', time_window_reached: '时间窗口停止', checkpoint_reached: '增量检查点停止', detail_fetch_incomplete: '部分详情抓取失败',
  }[reason]
}
