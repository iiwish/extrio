import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Popover } from 'radix-ui'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  FileCheck2,
  Globe2,
  Plus,
  Search,
} from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { CollectorDetail, Run } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { collectorDisplayName, sourceLocationLabel } from './collector-presentation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

type CollectorFilter = 'all' | 'attention' | 'published'

const attentionRunStatuses = new Set(['partially_succeeded', 'failed', 'timed_out'])

function actionFor(collector: CollectorDetail, latestRun?: Run) {
  if (collector.status === 'draft') return { label: '开始 Source 探索', detail: '尚未生成候选规则', tone: 'warning' as const, icon: Globe2 }
  if (collector.status === 'ready_review') return { label: '完成字段审核', detail: '审核决定完成后才能发布', tone: 'warning' as const, icon: FileCheck2 }
  if (!collector.activeRuleVersion) return { label: '检查发布状态', detail: '当前没有可执行的活动规则', tone: 'danger' as const, icon: AlertTriangle }
  if (!latestRun) return { label: '执行首次运行', detail: '规则已发布，等待真实运行验证', tone: 'primary' as const, icon: Activity }
  if (attentionRunStatuses.has(latestRun.status) || latestRun.rejectedCount > 0) {
    return { label: '处理最近运行', detail: `${latestRun.acceptedCount} 接收 · ${latestRun.rejectedCount} 拒绝`, tone: 'danger' as const, icon: CircleAlert }
  }
  return { label: '运行健康', detail: `${latestRun.acceptedCount} 接收 · ${stopReasonLabel(latestRun.paginationStopReason)}`, tone: 'success' as const, icon: CheckCircle2 }
}

function needsAttention(collector: CollectorDetail, latestRun?: Run) {
  return collector.status !== 'published' || Boolean(latestRun && (attentionRunStatuses.has(latestRun.status) || latestRun.rejectedCount > 0))
}

export function CollectorsPage() {
  const query = useQuery({ queryKey: ['collectors'], queryFn: api.collectors })
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  const [searchParams, setSearchParams] = useSearchParams()
  const filter = (searchParams.get('view') as CollectorFilter | null) ?? 'all'
  const collectionFilter = searchParams.get('collection') ?? 'all'
  const collectors = query.data ?? []
  const runsById = new Map((runsQuery.data ?? []).map((run) => [run.id, run]))
  const latestRunFor = (collector: CollectorDetail) => collector.latestRunId ? runsById.get(collector.latestRunId) : undefined
  const collections = Array.from(new Map(collectors.map((collector) => [collector.collectionId, {
    id: collector.collectionId,
    name: collector.collectionName,
    version: collector.collectionVersion,
  }])).values())
  const filtered = collectors.filter((collector) => {
    const matchesCollection = collectionFilter === 'all' || collector.collectionId === collectionFilter
    const matchesView = filter === 'all' || (filter === 'attention' ? needsAttention(collector, latestRunFor(collector)) : collector.status === 'published')
    return matchesCollection && matchesView
  })
  const attentionCount = collectors.filter((collector) => needsAttention(collector, latestRunFor(collector))).length
  const publishedCount = collectors.filter((collector) => collector.status === 'published').length
  const createCollectorPath = collectionFilter === 'all'
    ? '/collectors/new'
    : `/collectors/new?collection=${encodeURIComponent(collectionFilter)}`

  function updateParams(updates: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    Object.entries(updates).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
    setSearchParams(next)
  }

  function setFilter(next: CollectorFilter) {
    updateParams({ view: next === 'all' ? null : next })
  }

  return (
    <div className="page-frame entity-page collectors-page">
      <h1 className="sr-only">采集器</h1>
      <div className="filter-card collector-toolbar" aria-label="采集器工具栏">
        <div className="segmented" role="group" aria-label="Collector 筛选">
          <Button variant={filter === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => setFilter('all')}>全部 <span>{collectors.length}</span></Button>
          <Button variant={filter === 'attention' ? 'secondary' : 'ghost'} size="sm" onClick={() => setFilter('attention')}>需处理 <span>{attentionCount}</span></Button>
          <Button variant={filter === 'published' ? 'secondary' : 'ghost'} size="sm" onClick={() => setFilter('published')}>已发布 <span>{publishedCount}</span></Button>
        </div>
        <div className="collector-view-controls">
          <CollectionCombobox value={collectionFilter} collections={collections} onValueChange={(value) => updateParams({ collection: value === 'all' ? null : value })} />
          <Button asChild size="sm"><Link to={createCollectorPath}><Plus />新建采集器</Link></Button>
        </div>
      </div>

      <section className="object-list collector-object-list" aria-label="Collector 列表">
        <div className="object-list-head collector-list-grid" aria-hidden="true">
          <span>采集器</span><span>所属需求</span><span>状态</span><span>活动规则</span><span>最近运行</span><span>下一步</span><span />
        </div>
        {(query.isLoading || runsQuery.isLoading) && Array.from({ length: 5 }, (_, index) => <Skeleton className="collector-list-skeleton" key={index} />)}
        {!query.isLoading && !runsQuery.isLoading && filtered.map((collector) => <CollectorRow collector={collector} latestRun={latestRunFor(collector)} key={collector.id} />)}
        {!query.isLoading && !runsQuery.isLoading && filtered.length === 0 && <div className="card-empty collector-list-empty">当前筛选下没有采集器。</div>}
      </section>
    </div>
  )
}

function CollectionCombobox({ value, collections, onValueChange }: {
  value: string
  collections: Array<{ id: string; name: string; version: string }>
  onValueChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const options = [{ id: 'all', name: '全部需求', version: '' }, ...collections]
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const filteredOptions = normalizedQuery
    ? options.filter((option) => `${option.name} ${option.version}`.toLocaleLowerCase().includes(normalizedQuery))
    : options
  const selected = options.find((option) => option.id === value) ?? options[0]

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) setQuery('')
  }

  function selectCollection(id: string) {
    onValueChange(id)
    handleOpenChange(false)
  }

  return <Popover.Root open={open} onOpenChange={handleOpenChange}>
    <Popover.Trigger asChild>
      <Button className="collection-combobox-trigger" variant="outline" size="sm" role="combobox" aria-label="按采集需求筛选" aria-expanded={open}>
        <span>{selected.name}</span><ChevronDown />
      </Button>
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content className="collection-combobox-content" align="end" sideOffset={4} onOpenAutoFocus={(event) => { event.preventDefault(); inputRef.current?.focus() }}>
        <div className="collection-combobox-search"><Search /><Input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索需求名称或版本" aria-label="搜索采集需求" /></div>
        <div className="collection-combobox-options" role="listbox" aria-label="采集需求">
          {filteredOptions.map((option) => <button type="button" role="option" aria-selected={option.id === value} className="collection-combobox-option" onClick={() => selectCollection(option.id)} key={option.id}>
            <span><strong>{option.name}</strong>{option.version && <small>{option.version}</small>}</span>
            {option.id === value && <Check />}
          </button>)}
          {filteredOptions.length === 0 && <p className="collection-combobox-empty">未找到采集需求</p>}
        </div>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>
}

function CollectorRow({ collector, latestRun }: { collector: CollectorDetail; latestRun?: Run }) {
  const action = actionFor(collector, latestRun)
  const ActionIcon = action.icon
  return <Link className="object-row collector-list-grid collector-list-row" to={`/collectors/${collector.id}`}>
    <span className="object-primary"><span className="source-icon"><Globe2 /></span><span><strong>{collectorDisplayName(collector.name)}</strong><small>{sourceLocationLabel(collector.sourceUrl, collector.sourceHost)}</small></span></span>
    <span className="collector-list-collection"><strong>{collector.collectionName}</strong><small>{collector.collectionVersion}</small></span>
    <StatusBadge status={collector.status} />
    <span className="collector-list-fact"><strong>{collector.activeRuleVersion ?? '尚未发布'}</strong><small>{collector.collectionPolicy ? `策略 v${collector.collectionPolicy.version}` : '等待建立策略'}</small></span>
    <span className={`collector-list-fact ${latestRun && (attentionRunStatuses.has(latestRun.status) || latestRun.rejectedCount > 0) ? 'danger' : ''}`}><strong>{latestRun ? `${latestRun.status === 'succeeded' ? '成功' : latestRun.status} · ${latestRun.duration}` : '尚无运行'}</strong><small>{latestRun ? `${latestRun.acceptedCount} 接收 · ${latestRun.rejectedCount} 拒绝` : '等待首次运行'}</small></span>
    <span className={`collector-action-cell ${action.tone}`}><ActionIcon /><span><strong>{action.label}</strong><small>{action.detail}</small></span></span>
    <ArrowRight className="row-arrow" />
  </Link>
}

function stopReasonLabel(reason: Run['paginationStopReason']) {
  return {
    not_applicable: '单页完成',
    empty_page: '空页停止',
    next_link_exhausted: '已到末页',
    max_pages: '达到分页上限',
    max_items: '达到明细上限',
    budget_exhausted: '请求预算耗尽',
    cross_host_blocked: '跨主机已阻断',
    time_window_reached: '已到时间窗口',
    checkpoint_reached: '已到增量检查点',
    detail_fetch_incomplete: '部分详情抓取失败',
  }[reason]
}
