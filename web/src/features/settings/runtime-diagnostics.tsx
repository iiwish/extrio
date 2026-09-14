import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check, RefreshCw, Server } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { QueryError } from '@/components/query-error'
import { Skeleton } from '@/components/ui/skeleton'

export function RuntimeDiagnosticsSection() {
  const { t, i18n } = useTranslation('settings')
  const query = useQuery({ queryKey: ['runtime'], queryFn: api.runtime, refetchInterval: 5000 })
  const state = query.data
  return <section className="settings-runtime" aria-label={t('runtime.title')}>
    <header><h2><Server />{t('runtime.title')}</h2><Button variant="ghost" size="icon-sm" aria-label={t('runtime.refresh')} title={t('runtime.refresh')} disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw className={query.isFetching ? 'animate-spin' : ''} /></Button></header>
    <QueryError error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
    {query.isPending && <Skeleton className="h-24 w-full" />}
    {state && <>
      <div className={`runtime-state ${state.ready ? 'success' : 'warning'}`}>{state.ready ? <Check /> : <AlertTriangle />}<strong>{state.ready ? t('runtime.ready') : t(`runtime.reason.${state.reason}`)}</strong></div>
      {!state.ready && state.reason && <p className="runtime-recovery">{t(`runtime.recovery.${state.reason}`)}</p>}
      <dl className="runtime-facts">
        <div><dt>{t('runtime.liveWorkers')}</dt><dd>{state.liveWorkers}</dd></div>
        <div><dt>{t('runtime.queued')}</dt><dd>{state.queue?.queuedJobs ?? '-'}</dd></div>
        <div><dt>{t('runtime.running')}</dt><dd>{state.queue?.runningJobs ?? '-'}</dd></div>
        <div><dt>{t('runtime.oldest')}</dt><dd>{t('runtime.seconds', { count: state.queue?.oldestDueSeconds ?? 0 })}</dd></div>
      </dl>
      {(state.workers ?? []).map((worker) => <div className="runtime-worker" key={worker.id}><code>{worker.id}</code><span>{t(worker.deploymentMatches ? 'runtime.matched' : 'runtime.mismatched')}</span><time>{new Date(worker.lastSeen).toLocaleString(i18n.language)}</time></div>)}
    </>}
  </section>
}
