import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, ArrowRightLeft, Ellipsis, LoaderCircle, Pencil, RefreshCw, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, ApiRequestError } from '@/api/client'
import type { CollectionAttribution, CollectorDetail, CollectorLifecycleInput, CollectorReassignmentPlan } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { returnTarget, useWorkspaceLink } from '@/lib/workspace-navigation'
import { FieldContractValue } from '@/features/collections/collection-field-tools'

type Action = CollectorLifecycleInput['action'] | 'reassign'

export function ArchivedBadge() {
  const { t } = useTranslation('collectors')
  return <Badge variant="outline">{t('management.archived')}</Badge>
}

export function DeletedSourceBadge() {
  const { t } = useTranslation('collectors')
  return <Badge variant="outline" title={t('management.deletedNotice')}>{t('management.deleted')}</Badge>
}

export function HistoryAttribution({ value }: { value?: CollectionAttribution }) {
  const { t } = useTranslation('collectors')
  const workspaceLink = useWorkspaceLink()
  return <span className="history-attribution">{t('management.historyRequirement')}: {value ? <><Link to={workspaceLink(`/collections/${encodeURIComponent(value.collectionId)}`)}>{value.collectionName}</Link><code>{value.collectionVersion}</code></> : t('management.historyUnknown')}</span>
}

export function ManagementError({ error }: { error: Error | null }) {
  const { t } = useTranslation('collectors')
  if (!error) return null
  return <Alert variant="destructive"><AlertDescription>{error instanceof ApiRequestError ? t(`management.blockers.${error.code}`, { defaultValue: error.message }) : error.message}</AlertDescription></Alert>
}

function Blockers({ codes }: { codes: string[] }) {
  const { t } = useTranslation('collectors')
  if (!codes.length) return null
  return <Alert variant="destructive"><AlertDescription><ul>{codes.map(code => <li key={code}>{t(`management.blockers.${code}`, { defaultValue: code })}</li>)}</ul></AlertDescription></Alert>
}

export function CollectorManagement({ collector }: { collector: CollectorDetail }) {
  const { t } = useTranslation('collectors')
  const { user } = useAuth()
  const [action, setAction] = useState<Action | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const workspaceLink = useWorkspaceLink()
  if (user.role !== 'administrator' && user.role !== 'engineer') return null
  const archived = collector.lifecycle === 'archived'
  function edit() {
    const target = `/collectors/${encodeURIComponent(collector.id)}`
    if (location.pathname === target) {
      const next = new URLSearchParams(params); next.set('section', 'config'); next.set('edit', 'definition')
      navigate(`${target}?${next}`)
    } else navigate(workspaceLink(`${target}?section=config&edit=definition`))
  }
  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button ref={trigger} className="collector-management-trigger" size="icon-sm" variant="ghost" title={t('management.menu', { name: collector.name })} aria-label={t('management.menu', { name: collector.name })}><Ellipsis /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end" onCloseAutoFocus={event => { if (action) event.preventDefault() }}>
        {!archived && <DropdownMenuItem onSelect={edit}><Pencil />{t('management.edit')}</DropdownMenuItem>}
        {!archived && <DropdownMenuItem onSelect={() => setAction('reassign')}><ArrowRightLeft />{t('management.reassign')}</DropdownMenuItem>}
        <DropdownMenuItem onSelect={() => setAction(archived ? 'restore' : 'archive')}>{archived ? <ArchiveRestore /> : <Archive />}{t(`management.${archived ? 'restore' : 'archive'}`)}</DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onSelect={() => setAction('delete')}><Trash2 />{t('management.delete')}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    {action && <ManagementDialog collector={collector} action={action} onClose={() => setAction(null)} onRestoreFocus={() => trigger.current?.focus()} />}
  </>
}

function ManagementDialog({ collector, action, onClose, onRestoreFocus }: { collector: CollectorDetail; action: Action; onClose: () => void; onRestoreFocus: () => void }) {
  const { t } = useTranslation('collectors')
  const client = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const [target, setTarget] = useState('')
  const [name, setName] = useState('')
  const [confirmation, setConfirmation] = useState<{ digest: string; keys: string[] }>({ digest: '', keys: [] })
  const submission = useRef<{ body: string; key: string } | null>(null)
  const moving = action === 'reassign'
  const lifecycle = useQuery({ queryKey: ['collector-lifecycle', collector.id], queryFn: () => api.collectorLifecyclePlan(collector.id), enabled: !moving, staleTime: 0, refetchOnWindowFocus: false })
  const collections = useQuery({ queryKey: ['collections'], queryFn: api.collections, enabled: moving })
  const reassignment = useQuery({ queryKey: ['collector-reassignment', collector.id, target], queryFn: () => api.collectorReassignmentPlan(collector.id, target), enabled: moving && Boolean(target), staleTime: 0, refetchOnWindowFocus: false })
  const mutation = useMutation({
    mutationFn: (confirmedChanges: string[]) => {
      const payload = moving ? { targetCollectionId: target, planDigest: reassignment.data!.planDigest, confirmedChanges } : { action: action as CollectorLifecycleInput['action'], planDigest: lifecycle.data!.planDigest }
      const body = JSON.stringify(payload)
      if (submission.current?.body !== body) submission.current = { body, key: crypto.randomUUID() }
      return moving ? api.reassignCollector(collector.id, payload as Parameters<typeof api.reassignCollector>[1], submission.current.key) : api.changeCollectorLifecycle(collector.id, payload as CollectorLifecycleInput, submission.current.key)
    },
    onSuccess: async value => {
      if ('deleted' in value) {
        client.removeQueries({ queryKey: ['collector', collector.id] })
        if (location.pathname === `/collectors/${collector.id}`) navigate(returnTarget(params, '/collectors'), { replace: true })
      } else client.setQueryData(['collector', collector.id], value)
      for (const key of ['collectors', 'collections', 'collection', 'overview', 'runs', 'run', 'items', 'item', 'ai-runs', 'ai-run', 'operation']) await client.invalidateQueries({ queryKey: [key] })
      onClose()
    },
  })
  const pending = mutation.isPending
  const plan = moving ? reassignment.data : lifecycle.data
  const fetching = moving ? reassignment.isFetching : lifecycle.isFetching
  const error = moving ? reassignment.error ?? collections.error : lifecycle.error
  const blocked = action === 'delete' ? lifecycle.data?.deleteBlockers ?? [] : lifecycle.data?.blockers ?? []
  const targets = (collections.data ?? []).filter(item => item.id !== collector.collectionId && item.status === 'active')
  const confirmed = reassignment.data?.planDigest === confirmation.digest ? confirmation.keys : []
  function refresh() {
    if (pending) return
    mutation.reset()
    setName('')
    setConfirmation({ digest: '', keys: [] })
    if (moving && target) void reassignment.refetch()
    else if (moving) void collections.refetch()
    else void lifecycle.refetch()
  }
  return <Dialog open onOpenChange={open => { if (!open && !pending) onClose() }}>
    <DialogContent className={`collector-management-dialog ${moving ? 'reassignment-dialog' : ''}`} showCloseButton={!pending} onInteractOutside={event => event.preventDefault()} onEscapeKeyDown={event => { if (pending) event.preventDefault() }} onCloseAutoFocus={event => { event.preventDefault(); onRestoreFocus() }}>
      <DialogHeader><DialogTitle>{t(`management.${action}`)}</DialogTitle><DialogDescription>{t(`management.${action}Description`)}</DialogDescription></DialogHeader>
      <div className="collector-management-body">
        {moving && <label className="field-group"><span>{t('management.target')}</span><select aria-label={t('management.target')} className="management-target-select" value={target} disabled={pending || collections.isFetching} onChange={event => { setTarget(event.target.value); mutation.reset() }}><option value="">{t('management.chooseTarget')}</option>{targets.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}
        {moving && collections.isSuccess && !targets.length && <p>{t('management.noTargets')}</p>}
        {fetching && <p role="status"><LoaderCircle className="animate-spin inline" size={16} /> {t('management.loading')}</p>}
        <ManagementError error={error} />
        {plan && !fetching && !error && <dl className="management-facts"><div><dt>{t('management.source')}</dt><dd>{plan.collectorName}</dd></div><div><dt>URL</dt><dd><code>{plan.sourceUrl}</code></dd></div></dl>}
        {!moving && lifecycle.data && !fetching && !error && <>
          <Blockers codes={blocked} />
          {action === 'delete' && <>
            {blocked.length > 0 ? <p className="management-impact">{t('management.deleteBlocked')}</p> : <>
              <p className="management-impact">{t('management.deleteImpact')} {lifecycle.data.scheduleEnabled && <span>{t('management.deleteSchedule')}</span>}</p>
              <section aria-label={t('management.retainedHistory')}>
                <strong>{t('management.retainedHistory')}</strong>
                <dl className="management-history">{Object.entries(lifecycle.data.historyCounts ?? {}).map(([key, count]) => <div key={key}><dt>{t(`management.history.${key}`, { defaultValue: key })}</dt><dd>{count}</dd></div>)}</dl>
                <p className="management-impact">{t('management.deleteHistory')}</p>
              </section>
              <label className="field-group"><span>{t('management.confirmName')}</span><Input value={name} disabled={pending} onChange={event => setName(event.target.value)} aria-label={t('management.confirmName')} autoComplete="off" /></label>
            </>}
          </>}
        </>}
        {moving && reassignment.data && !fetching && !error && <ReassignmentReview plan={reassignment.data} confirmed={confirmed} onConfirm={keys => setConfirmation({ digest: reassignment.data!.planDigest, keys })} pending={pending} error={mutation.error} onSubmit={changes => mutation.mutate(changes)} />}
        {!moving && <ManagementError error={mutation.error} />}
      </div>
      <DialogFooter>
        <Button variant="ghost" size="icon-sm" title={t('management.reload')} aria-label={t('management.reload')} disabled={pending || fetching} onClick={refresh}><RefreshCw /></Button>
        <Button variant="outline" disabled={pending} onClick={onClose}>{t('common:action.cancel')}</Button>
        {moving ? <Button type="submit" form="collector-reassignment-review" disabled={pending || fetching || Boolean(error) || !reassignment.data || reassignment.data.blockers.length > 0 || confirmed.length !== reassignment.data.changes.length}>{pending && <LoaderCircle className="animate-spin" />}{t('management.reassign')}</Button>
          : <Button variant={action === 'delete' ? 'destructive' : 'default'} disabled={pending || fetching || Boolean(error) || !lifecycle.data || blocked.length > 0 || (action === 'delete' && name !== lifecycle.data?.collectorName)} onClick={() => mutation.mutate([])}>{pending && <LoaderCircle className="animate-spin" />}{t(`management.${action}`)}</Button>}
      </DialogFooter>
    </DialogContent>
  </Dialog>
}

function ReassignmentReview({ plan, confirmed, onConfirm, pending, error, onSubmit }: { plan: CollectorReassignmentPlan; confirmed: string[]; onConfirm: (keys: string[]) => void; pending: boolean; error: Error | null; onSubmit: (changes: string[]) => void }) {
  const { t } = useTranslation('collectors')
  return <form id="collector-reassignment-review" onSubmit={event => { event.preventDefault(); if (!pending && !plan.blockers.length && confirmed.length === plan.changes.length) onSubmit(confirmed) }}>
    <dl className="management-facts"><div><dt>{t('management.from')}</dt><dd>{plan.fromCollectionName}</dd></div><div><dt>{t('management.target')}</dt><dd>{plan.targetCollectionName}<code>{plan.targetVersionId}</code></dd></div><div><dt>{t('management.intent')}</dt><dd>{plan.targetIntent}</dd></div></dl>
    <Blockers codes={plan.blockers} />
    {plan.unresolvedHistory.length > 0 && <ul>{plan.unresolvedHistory.map(item => <li key={`${item.type}:${item.id}`}><code>{item.type}: {item.id}</code></li>)}</ul>}
    <p className="management-impact">{t(plan.requiresRecompile ? 'management.recompile' : 'management.emptyMove')}</p>
    <dl className="management-history">{Object.entries(plan.historyCounts).map(([key, count]) => <div key={key}><dt>{t(`management.history.${key}`, { defaultValue: key })}</dt><dd>{count}</dd></div>)}</dl>
    {plan.changes.length > 0 ? <table className="management-diff"><thead><tr><th>{t('management.field')}</th><th>{t('management.before')}</th><th>{t('management.after')}</th></tr></thead><tbody>{plan.changes.map(change => <tr key={change.key}><td><label><input type="checkbox" required disabled={pending} checked={confirmed.includes(change.key)} onChange={event => onConfirm(event.target.checked ? [...confirmed, change.key] : confirmed.filter(key => key !== change.key))} />{change.key}<small>{t(`management.change.${change.kind}`)}</small></label></td><td><FieldContractValue field={change.before} /></td><td><FieldContractValue field={change.after} /></td></tr>)}</tbody></table> : <p>{t('management.noChanges')}</p>}
    <ManagementError error={error} />
  </form>
}
