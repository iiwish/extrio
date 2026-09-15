import { Archive, ArrowDown, ArrowUp, Check, ChevronRight, FileText, Plus, RefreshCw, Search, X } from 'lucide-react'
import { useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import { ListWorkspace } from '@/components/list-workspace'
import { useListQuery } from '@/lib/use-list-query'
import { useAuth } from '@/features/auth/auth-gate'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

const statuses = ['active', 'archived', 'all'] as const

export function CollectionsPage() {
  const { t, i18n } = useTranslation('common')
  const { user } = useAuth()
  const [params] = useSearchParams()
  const searchRef = useRef<HTMLInputElement>(null)
  const search = params.get('q') ?? ''
  const status = statuses.find(value => value === params.get('status')) ?? 'active'
  const ascending = params.get('sort') === 'updated_asc'
  const list = useListQuery({ queryKey: ['collections', 'list', status, search, ascending],
    queryFn: (page, signal) => api.collectionsPage({ ...page, status, q: search.trim() || undefined, sort: ascending ? 'updated_asc' : 'updated_desc' }, signal) })
  const { query } = list
  const collections = query.data?.items ?? []
  const term = search.trim().toLocaleLowerCase()
  const filtered = collections
  const canEdit = user.role === 'administrator' || user.role === 'engineer'
  const counts = query.data?.counts
  const dateFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { year: 'numeric', month: '2-digit', day: '2-digit' })
  const timeFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { hour: '2-digit', minute: '2-digit', hour12: false })

  function updateParam(key: string, value: string, replace = false) {
    list.updateParams({ [key]: value || null }, replace)
  }

  function clearSearch() {
    updateParam('q', '', true)
    searchRef.current?.focus()
  }

  const emptyTitle = counts?.all === 0 ? 'collections.empty'
    : term ? 'collections.noMatches'
      : status === 'archived' ? 'collections.noArchived' : 'collections.noActive'

  return <ListWorkspace className="page-frame collections-page" label={t('nav.collections')}
    count={query.data?.total} loading={query.isPending} refreshing={query.isFetching} failed={query.isError} resetKey={list.resetKey} pagination={list.pagination}
    toolbar={<TooltipProvider delayDuration={300}>
      <div className="collections-toolbar" aria-label={t('collections.toolbar')}>
        <div className="collection-status-filter" role="group" aria-label={t('collections.statusFilter')}>
          {statuses.map(value => <Button key={value} variant="ghost" size="sm" aria-pressed={status === value}
            onClick={() => updateParam('status', value)}>
            {t(`collections.${value}`)}<span className="collection-status-count">{counts?.[value] ?? '—'}</span>
          </Button>)}
        </div>
        <div className="collection-list-tools">
          <div className="collections-search">
            <Search size={16} aria-hidden="true" />
            <Input ref={searchRef} aria-label={t('collections.search')} placeholder={t('collections.searchPlaceholder')}
              value={search} onChange={event => updateParam('q', event.target.value, true)} />
            {search && <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={t('collections.clearSearch')} onClick={clearSearch}><X /></Button></TooltipTrigger><TooltipContent>{t('collections.clearSearch')}</TooltipContent></Tooltip>}
          </div>
          <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={t('collections.refresh')}
            disabled={query.isFetching} onClick={() => query.refetch()}><RefreshCw className={query.isFetching ? 'animate-spin motion-reduce:animate-none' : undefined} /></Button></TooltipTrigger><TooltipContent>{t('collections.refresh')}</TooltipContent></Tooltip>
          {canEdit && <Button asChild size="sm"><Link to="/collections/new"><Plus />{t('collections.create')}</Link></Button>}
        </div>
      </div>
    </TooltipProvider>}
    notices={query.isError && <Alert variant="destructive" className="collection-list-error">
      <AlertTitle>{t('collections.loadFailed')}</AlertTitle>
      <AlertDescription>{query.error.message}</AlertDescription>
      <Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => query.refetch()}><RefreshCw />{t('action.retry')}</Button>
    </Alert>}>
    <h1 className="sr-only">{t('nav.collections')}</h1>
    {query.isPending ? <div className="collection-list-loading" aria-label={t('state.loading')}>
      {[0, 1, 2].map(key => <div key={key}><Skeleton className="h-5 w-52" /><Skeleton className="mt-3 h-3 w-3/5" /></div>)}
    </div> : query.data && <div className="collections-table-scroll">
      <table className="collections-table">
        <caption className="sr-only">{t('nav.collections')}</caption>
        <thead><tr>
          <th scope="col">{t('nav.collections')}</th>
          <th scope="col">{t('collections.sourcePublication')}</th>
          <th scope="col" aria-sort={ascending ? 'ascending' : 'descending'}>
            <button className="collection-sort" onClick={() => updateParam('sort', ascending ? '' : 'updated_asc')}
              title={t(ascending ? 'collections.newestFirst' : 'collections.oldestFirst')}>
              {t('collections.updatedAt')}{ascending ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
            </button>
          </th>
          <th scope="col">{t('collections.contractReference')}</th>
        </tr></thead>
        <tbody>{filtered.map(row => {
          const date = new Date(row.updatedAt)
          const pendingSources = Math.max(0, row.sourceCount - row.publishedSourceCount)
          const allPublished = row.sourceCount > 0 && pendingSources === 0
          return <tr key={row.id}>
            <td><div className="collection-list-identity">
              <span className="collection-list-icon" aria-hidden="true">{row.status === 'archived' ? <Archive size={17} /> : <FileText size={17} />}</span>
              <div className="collection-list-description">
                <div className="collection-list-name">
                  <Link title={row.name} to={`/collections/${encodeURIComponent(row.id)}${params.size ? `?${params}` : ''}`}><strong>{row.name}</strong><ChevronRight size={14} aria-hidden="true" /></Link>
                  {row.status === 'archived' && <span className="collection-archived">{t('collections.archived')}</span>}
                </div>
                <p className="collection-intent" title={row.intent}>{row.intent}</p>
              </div>
            </div></td>
            <td><div className={`collection-publication ${allPublished ? 'is-complete' : pendingSources ? 'is-pending' : 'is-empty'}`}>
              {row.sourceCount > 0 ? <>
                <span className="collection-publication-value"><strong>{row.publishedSourceCount}</strong><span>/ {row.sourceCount}</span><span>{t('collections.publishedShort')}</span></span>
                <span className="collection-publication-note">{allPublished && <Check size={13} aria-hidden="true" />}{t(allPublished ? 'collections.allPublished' : 'collections.pendingSources', { count: pendingSources })}</span>
              </> : <span>{t('collections.noSourcesShort')}</span>}
            </div></td>
            <td>{Number.isNaN(date.getTime()) ? '—' : <time className="collection-updated" dateTime={row.updatedAt}>
              <span>{dateFormat.format(date)}</span><span>{timeFormat.format(date)}</span>
            </time>}</td>
            <td><code className="collection-contract-reference" title={row.collectionVersion}>{row.collectionVersion}</code></td>
          </tr>
        })}</tbody>
      </table>
      {filtered.length === 0 && <div className="collections-empty">
        {status === 'archived' && !term ? <Archive size={28} aria-hidden="true" /> : term ? <Search size={28} aria-hidden="true" /> : <FileText size={28} aria-hidden="true" />}
        <h2>{t(emptyTitle)}</h2>
        {(counts?.all ?? 0) > 0 && (term
          ? <Button variant="outline" onClick={clearSearch}>{t('collections.showStatusResults')}</Button>
          : <Button variant="outline" onClick={() => updateParam('status', status === 'archived' ? 'active' : 'all')}>{t(status === 'archived' ? 'collections.showActive' : 'collections.showAll')}</Button>)}
      </div>}
    </div>}
  </ListWorkspace>
}
