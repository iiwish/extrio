import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ArrowRightLeft, Check, RefreshCw, Undo2 } from 'lucide-react'
import type { Collector, CollectionMigrationPlan } from '@/api/types'
import { api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { FieldContractValue } from './collection-field-tools'

export function CollectionMigration({ source, targetVersionId, canReview, busy = false }: { source: Collector; targetVersionId?: string | null; canReview: boolean; busy?: boolean }) {
  const { t } = useTranslation('common')
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const trigger = useRef<HTMLElement | null>(null)
  const captureFocus = () => { trigger.current = document.activeElement as HTMLElement | null }
  const restoreFocus = () => trigger.current?.focus()
  const invalidate = async () => {
    await client.invalidateQueries({ queryKey: ['collection', source.collectionId] })
    await client.invalidateQueries({ queryKey: ['collector', source.id] })
    client.invalidateQueries({ queryKey: ['collectors'] })
  }
  const cancel = useMutation({ mutationFn: () => api.cancelCollectionMigration(source.id, { targetVersionId: source.pendingCollectionVersion! }), onSuccess: async () => { await invalidate(); setCancelOpen(false) } })
  const migration = source.collectionMigration
  if (source.lifecycle === 'archived') return null
  if (source.pendingCollectionVersion) return <div className="g2-migration-status"><strong>{t('g2.migrationPending', { version: migration?.targetVersionNumber })}</strong><span>{t(migration?.status === 'failed' ? 'g2.migrationFailed' : `g2.${migration?.status ?? 'awaiting_compile'}`)}</span>{canReview && <Button variant="ghost" size="sm" disabled={busy || Boolean(source.activeOperationId)} onClick={() => { captureFocus(); cancel.reset(); setCancelOpen(true) }}><Undo2 />{t('g2.cancelMigration')}</Button>}<Dialog open={cancelOpen} onOpenChange={(value) => { if (!cancel.isPending) setCancelOpen(value) }}><DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); restoreFocus() }}><DialogHeader><DialogTitle>{t('g2.cancelMigration')}</DialogTitle><DialogDescription>{t('g2.cancelMigrationNotice')}</DialogDescription></DialogHeader>{cancel.error && <Alert variant="destructive"><AlertDescription>{cancel.error.message}</AlertDescription></Alert>}<div className="g2-workflow-actions justify-end"><Button variant="outline" disabled={cancel.isPending} onClick={() => setCancelOpen(false)}>{t('action.cancel')}</Button><Button variant="destructive" disabled={cancel.isPending} onClick={() => cancel.mutate()}>{t('g2.confirmCancelMigration')}</Button></div></DialogContent></Dialog></div>
  if (!canReview || !targetVersionId || targetVersionId === source.collectionVersion) return null
  return <><Button size="sm" variant="outline" onClick={() => { captureFocus(); setOpen(true) }}><ArrowRightLeft />{t('g2.migration')}</Button>{open && <MigrationDialog source={source} targetVersionId={targetVersionId} onClose={() => setOpen(false)} onSuccess={invalidate} restoreFocus={restoreFocus} />}</>
}

function MigrationDialog({ source, targetVersionId, onClose, onSuccess, restoreFocus }: { source: Collector; targetVersionId: string; onClose: () => void; onSuccess: () => Promise<void>; restoreFocus: () => void }) {
  const { t } = useTranslation('common')
  const [pending, setPending] = useState(false)
  const query = useQuery({ queryKey: ['collectionMigration', source.id, targetVersionId], queryFn: () => api.collectionMigrationPlan(source.id, targetVersionId), staleTime: 0, refetchOnWindowFocus: false })
  return <Dialog open onOpenChange={(open) => { if (!open && !pending) onClose() }}><DialogContent className="g2-workflow-dialog" onCloseAutoFocus={(event) => { event.preventDefault(); restoreFocus() }} onInteractOutside={(event) => event.preventDefault()}><DialogHeader><DialogTitle>{t('g2.migration')}</DialogTitle><DialogDescription>{t('g2.migrationNotice')}</DialogDescription></DialogHeader>{query.error ? <Alert variant="destructive"><AlertDescription>{query.error.message}<Button variant="outline" onClick={() => query.refetch()}><RefreshCw />{t('action.retry')}</Button></AlertDescription></Alert> : query.data ? <MigrationReview key={query.data.planDigest} plan={query.data} onBusy={setPending} onClose={onClose} onSuccess={onSuccess} reload={() => query.refetch()} /> : <p>{t('state.loading')}</p>}</DialogContent></Dialog>
}

function MigrationReview({ plan, onClose, onSuccess, reload, onBusy }: { plan: CollectionMigrationPlan; onClose: () => void; onSuccess: () => Promise<void>; reload: () => void; onBusy: (busy: boolean) => void }) {
  const { t } = useTranslation('common')
  const [confirmed, setConfirmed] = useState<string[]>([])
  const command = useMutation({ mutationFn: () => api.migrateCollectionVersion(plan.collectorId, { targetVersionId: plan.targetVersionId, planDigest: plan.planDigest, confirmedChanges: confirmed }), onSuccess: async () => { await onSuccess(); onClose() } })
  useEffect(() => { onBusy(command.isPending); return () => onBusy(false) }, [command.isPending, onBusy])
  return <><dl className="g2-version-pair"><div><dt>{t('g2.current')}</dt><dd><code>{plan.fromVersionId}</code></dd></div><div><dt>{t('g2.target')}</dt><dd>v{plan.targetVersionNumber}<code>{plan.targetVersionId}</code></dd></div></dl>
    {plan.blockers.length > 0 && <Alert variant="destructive"><AlertDescription>{plan.blockers.map((blocker) => t(`g2.blockers.${blocker}`, { defaultValue: blocker })).join(' · ')}</AlertDescription></Alert>}
    {command.error && <Alert variant="destructive"><AlertDescription>{command.error.message}</AlertDescription></Alert>}
    {plan.changes.length === 0 ? <p>{t('g2.noChanges')}</p> : <div className="g2-diff-scroll"><table className="g2-diff-table"><thead><tr><th>{t('fields.key')}</th><th>{t('g2.before')}</th><th>{t('g2.after')}</th></tr></thead><tbody>{plan.changes.map((change) => <tr key={change.key}><td><label className="g2-field-select"><Checkbox aria-label={t('g2.reviewChange', { key: change.key })} checked={confirmed.includes(change.key)} disabled={command.isPending} onCheckedChange={(checked) => setConfirmed((keys) => checked ? [...keys, change.key] : keys.filter((key) => key !== change.key))} /><code>{change.key}</code></label><small>{t(`g2.${change.kind}`)}{change.breaking && ` · ${t('g2.breaking')}`}</small></td><td><FieldContractValue field={change.before} /></td><td><FieldContractValue field={change.after} /></td></tr>)}</tbody></table></div>}
    <div className="g2-workflow-actions justify-end"><Button size="icon-sm" variant="ghost" title={t('g2.refresh')} aria-label={t('g2.refresh')} disabled={command.isPending} onClick={() => { setConfirmed([]); command.reset(); reload() }}><RefreshCw /></Button><Button variant="outline" disabled={command.isPending} onClick={onClose}>{t('action.cancel')}</Button><Button disabled={command.isPending || plan.blockers.length > 0 || confirmed.length !== plan.changes.length} onClick={() => command.mutate()}><Check />{t('g2.beginMigration')}</Button></div>
  </>
}
