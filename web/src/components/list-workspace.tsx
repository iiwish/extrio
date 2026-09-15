import { useEffect, useRef, type ComponentProps, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { ListPagination } from './list-pagination'
import './list-workspace.css'

type ListWorkspaceProps = {
  label: string
  toolbar: ReactNode
  children: ReactNode
  className?: string
  count?: number
  total?: number
  partial?: boolean
  loading?: boolean
  refreshing?: boolean
  failed?: boolean
  showSummary?: boolean
  notices?: ReactNode
  footer?: ReactNode
  pagination?: ComponentProps<typeof ListPagination>
  resetKey?: string
}

export function ListWorkspace({ label, toolbar, children, className, count, total, partial = false, loading = false, refreshing = false, failed = false, showSummary = true, notices, footer, pagination, resetKey }: ListWorkspaceProps) {
  const { t } = useTranslation('common')
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [resetKey])
  const countLabel = count === undefined
    ? t(loading ? 'state.loading' : 'listWorkspace.unavailable')
    : total !== undefined && total !== count
      ? t('listWorkspace.loadedTotal', { count, total })
      : t(partial ? 'listWorkspace.loaded' : 'listWorkspace.count', { count })

  return <div className={cn('list-workspace', className)}>
    <div className="list-workspace-toolbar">{toolbar}</div>
    {showSummary && <div className="list-workspace-summary" role="status" aria-live="polite" aria-atomic="true">
      <span>{countLabel}</span>
      {failed && count !== undefined ? <span className="list-workspace-stale">{t('listWorkspace.stale')}</span> : refreshing && !loading && <span>{t('listWorkspace.refreshing')}</span>}
    </div>}
    {notices && <div className="list-workspace-notices">{notices}</div>}
    <div className="list-workspace-scroll" ref={scrollRef} role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
    {(pagination || footer) && <div className="list-workspace-footer">{pagination ? <ListPagination {...pagination} /> : footer}</div>}
  </div>
}
