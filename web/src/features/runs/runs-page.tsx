import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Clock3, PlayCircle, RefreshCw, Search } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { Run } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { collectorDisplayName } from '@/features/collectors/collector-presentation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

const attentionStatuses = ['partially_succeeded', 'failed', 'timed_out']

export function RunsPage() {
  const query = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  const [searchParams, setSearchParams] = useSearchParams()
  const filter = searchParams.get('status') ?? 'all'
  const search = searchParams.get('q') ?? ''
  const runs = query.data ?? []
  const normalizedSearch = search.trim().toLowerCase()
  const filtered = runs.filter((run) => {
    const matchesStatus = filter === 'all' || (filter === 'attention' ? attentionStatuses.includes(run.status) : run.status === 'succeeded')
    const matchesSearch = !normalizedSearch || `${run.collectorName} ${run.id}`.toLowerCase().includes(normalizedSearch)
    return matchesStatus && matchesSearch
  })
  const attentionCount = runs.filter((run) => attentionStatuses.includes(run.status)).length

  function updateParam(key: 'status' | 'q', value: string, emptyValue: string) {
    const next = new URLSearchParams(searchParams)
    if (!value || value === emptyValue) next.delete(key)
    else next.set(key, value)
    setSearchParams(next)
  }

  return (
    <div className="page-frame entity-page runs-page">
      <h1 className="sr-only">运行</h1>

      <div className="filter-card runs-toolbar" aria-label="运行工具栏">
        <div className="segmented" role="group" aria-label="Run 状态筛选">
          <Button variant={filter === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'all', 'all')}>全部 <span>{runs.length}</span></Button>
          <Button variant={filter === 'attention' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'attention', 'all')}>需处理 <span>{attentionCount}</span></Button>
          <Button variant={filter === 'succeeded' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('status', 'succeeded', 'all')}>完整成功 <span>{runs.filter((run) => run.status === 'succeeded').length}</span></Button>
        </div>
        <div className="runs-toolbar-actions">
          <div className="toolbar-search runs-search"><Search /><Input value={search} onChange={(event) => updateParam('q', event.target.value, '')} placeholder="搜索采集器名称或 Run ID" aria-label="搜索运行" /></div>
          <span className="filter-context"><Clock3 />按开始时间倒序</span>
          <Button variant="outline" size="icon-sm" aria-label="刷新" onClick={() => query.refetch()}><RefreshCw /></Button>
        </div>
      </div>

      <section className="object-list run-object-list" aria-label="Run 列表">
        <div className="object-list-head run-grid" aria-hidden="true">
          <span>运行</span><span>终态</span><span>接收</span><span>拒绝</span><span>范围与停止</span><span>开始 / 耗时</span><span />
        </div>
        {query.isLoading && Array.from({ length: 6 }, (_, index) => <Skeleton className="run-list-skeleton" key={index} />)}
        {filtered.map((run) => <RunRow run={run} key={run.id} />)}
        {!query.isLoading && filtered.length === 0 && <div className="card-empty run-list-empty">没有符合当前筛选和搜索的运行。</div>}
      </section>
    </div>
  )
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
        <span>
        <Badge variant="outline">{run.executionMode === 'incremental' ? '增量' : run.executionMode === 'initial' ? '首次' : '历史'}</Badge>
          <strong>{run.listPagesFetched} 列表页{run.collectionMode === 'list_detail' ? ` · ${run.detailPagesFetched}/${run.detailUrlsDiscovered} 详情页` : ''}</strong>
        </span>
        <small>{run.newItems + run.updatedItems} 条变更 · {stopReasonLabel(run.paginationStopReason)}</small>
      </span>
      <span className="run-time-cell"><strong>{run.startedAt}</strong><small>{run.duration}</small></span>
      <ArrowRight className="row-arrow" />
    </Link>
  )
}

function stopReasonLabel(reason: Run['paginationStopReason']) {
  return {
    not_applicable: '单页完成', empty_page: '空页停止', next_link_exhausted: '已到末页', max_pages: '达到分页上限', max_items: '达到明细上限', budget_exhausted: '请求预算耗尽', cross_host_blocked: '跨主机已阻断', time_window_reached: '时间窗口停止', checkpoint_reached: '增量检查点停止', detail_fetch_incomplete: '部分详情抓取失败',
  }[reason]
}
