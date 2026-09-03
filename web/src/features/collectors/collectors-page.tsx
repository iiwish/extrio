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
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { api } from '@/api/client'
import type { CollectorDetail, Run } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { StatusBadge } from '@/components/status-badge'
import { collectorDisplayName, sourceLocationLabel } from './collector-presentation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

type CollectorFilter = 'all' | 'attention' | 'published'

const attentionRunStatuses = new Set(['partially_succeeded', 'failed', 'timed_out'])

function actionFor(collector: CollectorDetail, latestRun: Run | undefined, t: TFunction<'collectors'>) {
  if (collector.status === 'draft') return { label: t('list.nextStep.startExploration'), detail: t('list.nextStep.startExplorationDetail'), tone: 'warning' as const, icon: Globe2 }
  if (collector.status === 'ready_review') return { label: t('list.nextStep.finishReview'), detail: t('list.nextStep.finishReviewDetail'), tone: 'warning' as const, icon: FileCheck2 }
  if (!collector.activeRuleVersion) return { label: t('list.nextStep.checkPublish'), detail: t('list.nextStep.checkPublishDetail'), tone: 'danger' as const, icon: AlertTriangle }
  if (!latestRun) return { label: t('list.nextStep.firstRun'), detail: t('list.nextStep.firstRunDetail'), tone: 'primary' as const, icon: Activity }
  if (attentionRunStatuses.has(latestRun.status) || latestRun.rejectedCount > 0) {
    return { label: t('list.nextStep.handleLatestRun'), detail: t('list.run.acceptedRejected', { accepted: latestRun.acceptedCount, rejected: latestRun.rejectedCount }), tone: 'danger' as const, icon: CircleAlert }
  }
  return { label: t('list.nextStep.runHealthy'), detail: t('list.nextStep.runHealthyDetail', { accepted: latestRun.acceptedCount, reason: stopReasonLabel(latestRun.paginationStopReason, t) }), tone: 'success' as const, icon: CheckCircle2 }
}

function needsAttention(collector: CollectorDetail, latestRun?: Run) {
  return collector.status !== 'published' || Boolean(latestRun && (attentionRunStatuses.has(latestRun.status) || latestRun.rejectedCount > 0))
}

export function CollectorsPage() {
  const { t } = useTranslation('collectors')
  const { user } = useAuth()
  const canCreateCollector = user.role !== 'viewer'
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
      <h1 className="sr-only">{t('common:nav.collectors')}</h1>
      <div className="filter-card collector-toolbar" aria-label={t('list.toolbarAria')}>
        <div className="segmented" role="group" aria-label={t('list.filterGroupAria')}>
          <Button variant={filter === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => setFilter('all')}>{t('list.filterAll')} <span>{collectors.length}</span></Button>
          <Button variant={filter === 'attention' ? 'secondary' : 'ghost'} size="sm" onClick={() => setFilter('attention')}>{t('list.filterAttention')} <span>{attentionCount}</span></Button>
          <Button variant={filter === 'published' ? 'secondary' : 'ghost'} size="sm" onClick={() => setFilter('published')}>{t('list.filterPublished')} <span>{publishedCount}</span></Button>
        </div>
        <div className="collector-view-controls">
          <CollectionCombobox value={collectionFilter} collections={collections} onValueChange={(value) => updateParams({ collection: value === 'all' ? null : value })} />
          {canCreateCollector && <Button asChild size="sm"><Link to={createCollectorPath}><Plus />{t('list.create')}</Link></Button>}
        </div>
      </div>

      <section className="object-list collector-object-list" aria-label={t('list.aria')}>
        <div className="object-list-head collector-list-grid" aria-hidden="true">
          <span>{t('list.columns.collector')}</span><span>{t('list.columns.requirement')}</span><span>{t('list.columns.status')}</span><span>{t('list.columns.activeRule')}</span><span>{t('list.columns.latestRun')}</span><span>{t('list.columns.nextStep')}</span><span />
        </div>
        {(query.isLoading || runsQuery.isLoading) && Array.from({ length: 5 }, (_, index) => <Skeleton className="collector-list-skeleton" key={index} />)}
        {!query.isLoading && !runsQuery.isLoading && filtered.map((collector) => <CollectorRow collector={collector} latestRun={latestRunFor(collector)} key={collector.id} />)}
        {!query.isLoading && !runsQuery.isLoading && filtered.length === 0 && <div className="card-empty collector-list-empty">{t('list.empty')}</div>}
      </section>
    </div>
  )
}

function CollectionCombobox({ value, collections, onValueChange }: {
  value: string
  collections: Array<{ id: string; name: string; version: string }>
  onValueChange: (value: string) => void
}) {
  const { t } = useTranslation('collectors')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const options = [{ id: 'all', name: t('list.requirement.all'), version: '' }, ...collections]
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
      <Button className="collection-combobox-trigger" variant="outline" size="sm" role="combobox" aria-label={t('list.requirement.filterAria')} aria-expanded={open}>
        <span>{selected.name}</span><ChevronDown />
      </Button>
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content className="collection-combobox-content" align="end" sideOffset={4} onOpenAutoFocus={(event) => { event.preventDefault(); inputRef.current?.focus() }}>
        <div className="collection-combobox-search"><Search /><Input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('list.requirement.searchPlaceholder')} aria-label={t('list.requirement.searchAria')} /></div>
        <div className="collection-combobox-options" role="listbox" aria-label={t('list.requirement.listAria')}>
          {filteredOptions.map((option) => <button type="button" role="option" aria-selected={option.id === value} className="collection-combobox-option" onClick={() => selectCollection(option.id)} key={option.id}>
            <span><strong>{option.name}</strong>{option.version && <small>{option.version}</small>}</span>
            {option.id === value && <Check />}
          </button>)}
          {filteredOptions.length === 0 && <p className="collection-combobox-empty">{t('list.requirement.empty')}</p>}
        </div>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>
}

function CollectorRow({ collector, latestRun }: { collector: CollectorDetail; latestRun?: Run }) {
  const { t } = useTranslation('collectors')
  const action = actionFor(collector, latestRun, t)
  const ActionIcon = action.icon
  return <Link className="object-row collector-list-grid collector-list-row" to={`/collectors/${collector.id}`}>
    <span className="object-primary"><span className="source-icon"><Globe2 /></span><span><strong>{collectorDisplayName(collector.name)}</strong><small>{sourceLocationLabel(collector.sourceUrl, collector.sourceHost)}</small></span></span>
    <span className="collector-list-collection"><strong>{collector.collectionName}</strong><small>{collector.collectionVersion}</small></span>
    <StatusBadge status={collector.status} />
    <span className="collector-list-fact"><strong>{collector.activeRuleVersion ?? t('list.rule.notPublished')}</strong><small>{collector.collectionPolicy ? t('list.rule.policyVersion', { version: collector.collectionPolicy.version }) : t('list.rule.noPolicy')}</small></span>
    <span className={`collector-list-fact ${latestRun && (attentionRunStatuses.has(latestRun.status) || latestRun.rejectedCount > 0) ? 'danger' : ''}`}><strong>{latestRun ? `${latestRun.status === 'succeeded' ? t('list.run.succeeded') : latestRun.status} · ${latestRun.duration}` : t('list.run.none')}</strong><small>{latestRun ? t('list.run.acceptedRejected', { accepted: latestRun.acceptedCount, rejected: latestRun.rejectedCount }) : t('list.run.awaitingFirst')}</small></span>
    <span className={`collector-action-cell ${action.tone}`}><ActionIcon /><span><strong>{action.label}</strong><small>{action.detail}</small></span></span>
    <ArrowRight className="row-arrow" />
  </Link>
}

function stopReasonLabel(reason: Run['paginationStopReason'], t: TFunction<'collectors'>) {
  return {
    not_applicable: t('list.stopReason.notApplicable'),
    empty_page: t('list.stopReason.emptyPage'),
    next_link_exhausted: t('list.stopReason.nextLinkExhausted'),
    max_pages: t('list.stopReason.maxPages'),
    max_items: t('list.stopReason.maxItems'),
    budget_exhausted: t('list.stopReason.budgetExhausted'),
    cross_host_blocked: t('list.stopReason.crossHostBlocked'),
    time_window_reached: t('list.stopReason.timeWindowReached'),
    checkpoint_reached: t('list.stopReason.checkpointReached'),
    detail_fetch_incomplete: t('list.stopReason.detailFetchIncomplete'),
  }[reason]
}
