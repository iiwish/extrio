import { useQuery } from '@tanstack/react-query'
import { Archive, ArrowDown, ArrowUp, Check, ChevronRight, FileText, Plus, RefreshCw, Search, X } from 'lucide-react'
import { useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
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
  const query = useQuery({ queryKey: ['collections'], queryFn: api.collections })
  const [params, setParams] = useSearchParams()
  const searchRef = useRef<HTMLInputElement>(null)
  const search = params.get('q') ?? ''
  const status = statuses.find(value => value === params.get('status')) ?? 'active'
  const ascending = params.get('sort') === 'updated_asc'
  const collections = query.data ?? []
  const term = search.trim().toLocaleLowerCase()
  const filtered = collections.filter(row => (status === 'all' || row.status === status)
    && `${row.name} ${row.intent}`.toLocaleLowerCase().includes(term))
    .sort((a, b) => {
      const difference = (Date.parse(a.updatedAt) || 0) - (Date.parse(b.updatedAt) || 0)
      return (ascending ? difference : -difference) || a.id.localeCompare(b.id)
    })
  const canEdit = user.role === 'administrator' || user.role === 'engineer'
  const counts = {
    active: collections.filter(row => row.status === 'active').length,
    archived: collections.filter(row => row.status === 'archived').length,
    all: collections.length,
  }
  const dateFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { year: 'numeric', month: '2-digit', day: '2-digit' })
  const timeFormat = new Intl.DateTimeFormat(i18n.resolvedLanguage, { hour: '2-digit', minute: '2-digit', hour12: false })

  function updateParam(key: string, value: string, replace = false) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace })
  }

  function clearSearch() {
    updateParam('q', '', true)
    searchRef.current?.focus()
  }

  const emptyTitle = collections.length === 0 ? 'collections.empty'
    : term ? 'collections.noMatches'
      : status === 'archived' ? 'collections.noArchived' : 'collections.noActive'

  return <div className="page-frame collections-page">
    <h1 className="sr-only">{t('nav.collections')}</h1>
    <TooltipProvider delayDuration={300}>
      <div className="collections-toolbar" aria-label={t('collections.toolbar')}>
        <div className="collection-status-filter" role="group" aria-label={t('collections.statusFilter')}>
          {statuses.map(value => <Button key={value} variant="ghost" size="sm" aria-pressed={status === value}
            onClick={() => updateParam('status', value)}>
            {t(`collections.${value}`)}<span className="collection-status-count">{query.isSuccess ? counts[value] : '—'}</span>
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
    </TooltipProvider>
    <div className="collection-list-summary">
      <span className="collections-total" role="status" aria-live="polite">
        {query.isPending ? t('state.loading') : query.isError ? t('collections.loadFailed') : t('collections.count', { count: filtered.length })}
      </span>
      {query.isFetching && !query.isPending && <span>{t('collections.refreshing')}</span>}
    </div>

    {query.isError ? <Alert variant="destructive" className="collection-list-error">
      <AlertTitle>{t('collections.loadFailed')}</AlertTitle>
      <AlertDescription>{query.error.message}</AlertDescription>
      <Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => query.refetch()}><RefreshCw />{t('action.retry')}</Button>
    </Alert> : query.isPending ? <div className="collection-list-loading" aria-label={t('state.loading')}>
      {[0, 1, 2].map(key => <div key={key}><Skeleton className="h-5 w-52" /><Skeleton className="mt-3 h-3 w-3/5" /></div>)}
    </div> : <div className="collections-table-scroll">
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
                  <Link to={`/collections/${encodeURIComponent(row.id)}${params.size ? `?${params}` : ''}`}><strong>{row.name}</strong><ChevronRight size={14} aria-hidden="true" /></Link>
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
            <td><code className="collection-contract-reference">{row.collectionVersion}</code></td>
          </tr>
        })}</tbody>
      </table>
      {filtered.length === 0 && <div className="collections-empty">
        {status === 'archived' && !term ? <Archive size={28} aria-hidden="true" /> : term ? <Search size={28} aria-hidden="true" /> : <FileText size={28} aria-hidden="true" />}
        <h2>{t(emptyTitle)}</h2>
        {collections.length > 0 && (term
          ? <Button variant="outline" onClick={clearSearch}>{t('collections.showStatusResults')}</Button>
          : <Button variant="outline" onClick={() => updateParam('status', status === 'archived' ? 'active' : 'all')}>{t(status === 'archived' ? 'collections.showActive' : 'collections.showAll')}</Button>)}
      </div>}
    </div>}
  </div>
}
