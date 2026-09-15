import { useMutation } from '@tanstack/react-query'
import { ArrowRight, Download, FileText, LoaderCircle, RefreshCw, Search, X } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiRequestError, api, exportItemsDownload, type ItemsQuery } from '@/api/client'
import type { ExportFormat, HarvestItem } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { ListWorkspace } from '@/components/list-workspace'
import { useListQuery } from '@/lib/use-list-query'
import { collectorDisplayName, collectorSourceLabel } from '@/features/collectors/collector-presentation'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import type { TFunction } from 'i18next'
import { useWorkspaceLink } from '@/lib/workspace-navigation'

export function ItemsPage() {
  const { t } = useTranslation('items')
  const [searchParams] = useSearchParams()
  const search = searchParams.get('q') ?? ''
  const decision = searchParams.get('decision') ?? 'all'
  const source = searchParams.get('source') ?? 'all'
  const collector = searchParams.get('collector') ?? 'all'
  const filters: ItemsQuery = {
    view: 'entities',
    collectorId: collector === 'all' ? undefined : collector,
    sourceHost: source === 'all' ? undefined : source,
    decision: decision === 'all' ? undefined : decision,
    q: search.trim() || undefined,
  }
  const list = useListQuery({
    queryKey: ['items', 'entities', filters],
    queryFn: (page, signal) => api.itemsPage({ ...filters, ...page }, signal),
  })
  const { query } = list
  const items = query.data?.items ?? []
  const firstPage = query.data
  const sources = firstPage?.facets?.sourceHosts ?? [...new Set(items.map(item => item.sourceHost))]
  const collectors = firstPage?.facets?.collectors ?? [...new Map(items.map(item => [item.collectorId, item.collectorName])).entries()].map(([id, name]) => ({ id, name }))

  function updateParam(key: string, value: string, emptyValue = 'all') {
    list.updateParams({ [key]: !value || value === emptyValue ? null : value })
  }

  const exportMutation = useMutation({
    mutationFn: async (format: ExportFormat) => {
      const blob = await exportItemsDownload({
        ...filters, format,
      })
      return { blob, format }
    },
    onSuccess: ({ blob, format }) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `extrio-items-${new Date().toISOString().slice(0, 10)}.${format}`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    },
  })

  return (
    <ListWorkspace className="page-frame entity-page items-page" label={t('list.aria')}
      count={firstPage?.total} loading={query.isLoading} refreshing={query.isFetching} failed={query.isError} resetKey={searchParams.toString()}
      pagination={list.pagination}
      toolbar={<div className="filter-card items-filter-card" aria-label={t('toolbar.aria')}>
        <div className="filter-cluster">
          <Select value={source} onValueChange={(value) => updateParam('source', value)}><SelectTrigger size="sm" aria-label={t('toolbar.sourceAria')}><SelectValue placeholder={t('toolbar.allSources')} /></SelectTrigger><SelectContent><SelectItem value="all">{t('toolbar.allSources')}</SelectItem>{sources.map((host) => <SelectItem key={host} value={host}>{host}</SelectItem>)}</SelectContent></Select>
          <Select value={collector} onValueChange={(value) => updateParam('collector', value)}><SelectTrigger size="sm" aria-label={t('toolbar.collectorAria')}><SelectValue placeholder={t('toolbar.allCollectors')} /></SelectTrigger><SelectContent><SelectItem value="all">{t('toolbar.allCollectors')}</SelectItem>{collectors.map(({ id, name }) => <SelectItem key={id} value={id}>{collectorDisplayName(name)}</SelectItem>)}</SelectContent></Select>
          <div className="segmented" role="group" aria-label={t('toolbar.decisionAria')}>
            <Button aria-pressed={decision === 'all'} variant={decision === 'all' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('decision', 'all')}>{t('toolbar.decisionAll')}</Button>
            <Button aria-pressed={decision === 'accepted'} variant={decision === 'accepted' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('decision', 'accepted')}>{t('common:status.accepted')}</Button>
            <Button aria-pressed={decision === 'rejected'} variant={decision === 'rejected' ? 'secondary' : 'ghost'} size="sm" onClick={() => updateParam('decision', 'rejected')}>{t('common:status.rejected')}</Button>
          </div>
        </div>
        <div className="items-filter-actions">
          <div className="toolbar-search items-search"><Search /><Input value={search} maxLength={500} onChange={(event) => updateParam('q', event.target.value, '')} placeholder={t('toolbar.searchPlaceholder')} aria-label={t('toolbar.searchAria')} />{search && <Button variant="ghost" size="icon-sm" aria-label={t('common:action.clearSearch')} title={t('common:action.clearSearch')} onClick={() => updateParam('q', '', '')}><X /></Button>}</div>
          <Button variant="outline" size="icon-sm" aria-label={t('common:action.refresh')} title={t('common:action.refresh')} disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw /></Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" disabled={exportMutation.isPending} aria-label={t('export.aria')}>
                {exportMutation.isPending ? <LoaderCircle className="animate-spin" /> : <Download />}{t('export.title')}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => exportMutation.mutate('csv')}>{t('export.csv')}</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => exportMutation.mutate('jsonl')}>{t('export.jsonl')}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>}
      notices={<>{exportMutation.error && (
        <Alert variant="destructive" className="mb-3">
          <AlertTitle>{t('export.title')}</AlertTitle>
          <AlertDescription>
            {exportMutation.error instanceof ApiRequestError && exportMutation.error.code === 'EXPORT_TOO_LARGE'
              ? t('export.tooLarge')
              : t('export.failed', { message: exportMutation.error.message })}
          </AlertDescription>
        </Alert>
      )}

      {query.error && <Alert variant="destructive"><AlertTitle>{t('list.loadFailed')}</AlertTitle><AlertDescription>{query.error.message}</AlertDescription><Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => query.refetch()}><RefreshCw />{t('list.retry')}</Button></Alert>}</>}>
      <h1 className="sr-only">{t('common:nav.items')}</h1>
      <div className="object-list item-object-list">
        <div className="object-list-head item-list-grid" aria-hidden="true">
          <span>{t('list.columnItem')}</span><span>{t('list.columnDecision')}</span><span>{t('list.columnChange')}</span><span>{t('list.columnPublished')}</span><span>{t('list.columnObserved')}</span><span>Entity key</span><span />
        </div>
        {query.isLoading && Array.from({ length: 6 }, (_, index) => <Skeleton className="item-list-skeleton" key={index} />)}
        {items.map((item) => <ItemRow item={item} key={item.id} />)}
        {query.isSuccess && items.length === 0 && <div className="card-empty item-list-empty">{t('list.empty')}</div>}
      </div>
    </ListWorkspace>
  )
}

function ItemRow({ item }: { item: HarvestItem }) {
  const { t } = useTranslation('items')
  const workspaceLink = useWorkspaceLink()
  return (
    <Link className={`object-row item-list-grid item-list-row ${item.decision === 'rejected' ? 'has-error' : ''}`} to={workspaceLink(`/items/${item.id}`)}>
      <span className="object-primary"><span className="source-icon"><FileText /></span><span><strong>{item.title}</strong><small>{item.collectorDeleted && <>{t('collectors:management.deleted')} · </>}{collectorSourceLabel(item.collectorName, item.sourceHost)}</small></span></span>
      <StatusBadge status={item.decision} />
      <span className="item-change-cell"><strong>{item.changeType ? changeTypeLabel(item.changeType, t) : t('list.noChange')}</strong><small>{item.revision === null ? t('list.noRevision') : t('list.revision', { count: item.revision })} · {t('list.observations', { count: item.observationHistory.length })}</small></span>
      <span className="item-time-cell"><strong>{item.publishedAt}</strong></span>
      <span className="item-time-cell"><strong>{item.observedAt}</strong></span>
      <code className="item-key-cell">{item.entityKey}</code>
      <ArrowRight className="row-arrow" />
    </Link>
  )
}

function changeTypeLabel(type: NonNullable<HarvestItem['changeType']>, t: TFunction) {
  return { new: t('list.change.new'), updated: t('list.change.updated'), unchanged: t('list.change.unchanged') }[type]
}

export function latestEntities(items: HarvestItem[]) {
  const latest = new Map<string, HarvestItem>()
  for (const item of items) {
    const key = `${item.collectorId}:${item.entityKey}`
    const current = latest.get(key)
    if (!current || item.observedAt > current.observedAt) latest.set(key, item)
  }
  return [...latest.values()].sort((left, right) => right.observedAt.localeCompare(left.observedAt))
}
