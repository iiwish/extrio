import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Square } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import { DetailPanel } from '@/components/detail-panel'
import { QueryError } from '@/components/query-error'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/auth-gate'

const active = ['cooling_down', 'running', 'cancelling']

export function RecoveryPanel({ runId, eligible }: { runId: string; eligible: boolean }) {
  const { t, i18n } = useTranslation('runs')
  const { user } = useAuth()
  const cache = useQueryClient()
  const key = ['run-recovery', runId]
  const query = useQuery({ queryKey: key, queryFn: () => api.runRecovery(runId),
    refetchInterval: q => q.state.data && active.includes(q.state.data.status) ? 2000 : false })
  const start = useMutation({ mutationFn: () => api.startRecovery(runId), onSuccess: value => cache.setQueryData(key, value),
    onSettled: () => { void cache.invalidateQueries({ queryKey: key }) } })
  const cancel = useMutation({ mutationFn: () => api.cancelRecovery(query.data!.id), onSuccess: value => cache.setQueryData(key, value),
    onSettled: () => { void cache.invalidateQueries({ queryKey: key }) } })
  const batch = query.data
  const canManage = ['administrator', 'engineer'].includes(user?.role ?? '')
  const time = (value: string | null) => value ? new Date(value).toLocaleString(i18n.language) : t('recovery.notScheduled')
  return <DetailPanel className="run-detail-section">
    <header><h2>{t('recovery.title')}</h2>{batch && <span role="status">{t(`recovery.status.${batch.status}`)}</span>}</header>
    <QueryError error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
    {query.isLoading && <p role="status">{t('recovery.loading')}</p>}
    {batch ? <>
      <dl className="run-scope-grid">
        <div><dt>{t('recovery.attempts')}</dt><dd>{batch.attemptRunIds.length} / {batch.maxAttempts}</dd></div>
        <div><dt>{t('recovery.resume')}</dt><dd>{t('coverage.resume', { page: batch.resumePage })}</dd></div>
        <div><dt>{t('recovery.next')}</dt><dd>{time(batch.nextAttemptAt)}</dd></div>
        <div><dt>{t('recovery.deadline')}</dt><dd>{time(batch.expiresAt)}</dd></div>
        <div><dt>{t('recovery.requests')}</dt><dd>{batch.reservedRequests} / {batch.maxRequests}</dd></div>
        <div><dt>{t('recovery.reason')}</dt><dd>{t(`recovery.reasonValue.${batch.reason}`, { defaultValue: batch.reason })}</dd></div>
      </dl>
      <div className="flex flex-wrap items-center gap-3">
        {batch.attemptRunIds.map((id, index) => <Link key={id} to={`/runs/${id}?section=scope`}>{t('recovery.attemptLink', { number: index + 1 })}</Link>)}
        {canManage && active.includes(batch.status) && <Button size="sm" variant="outline" disabled={cancel.isPending || batch.status === 'cancelling'} onClick={() => cancel.mutate()}><Square />{t('recovery.cancel')}</Button>}
      </div>
    </> : query.isSuccess && <>
      <dl className="run-scope-grid">
        <div><dt>{t('recovery.attempts')}</dt><dd>{t('recovery.defaultAttempts')}</dd></div>
        <div><dt>{t('recovery.cooldowns')}</dt><dd>{t('recovery.defaultCooldowns')}</dd></div>
        <div><dt>{t('recovery.budget')}</dt><dd>{t('recovery.defaultBudget')}</dd></div>
      </dl>
      {canManage && <Button size="sm" variant="outline" disabled={!eligible || start.isPending} onClick={() => start.mutate()}><RotateCcw />{t('recovery.start')}</Button>}
    </>}
    <QueryError error={start.error ?? cancel.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
  </DetailPanel>
}
