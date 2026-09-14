import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Check, ChevronDown, ChevronRight, FileText, Layers3, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Link, useBlocker, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useWorkspaceLink } from '@/lib/workspace-navigation'
import { useTranslation } from 'react-i18next'
import { useRef, useState } from 'react'
import { api, ApiRequestError } from '@/api/client'
import type { CollectionDetail, CollectionUpdateInput } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CollectionForm } from './collection-form'
import { CollectionFields } from './collection-fields'
import { CollectionMigration } from './collection-migration'
import { ArchivedBadge, CollectorManagement } from '@/features/collectors/collector-management'
import { CollectionSourceDialog } from './collection-source-dialog'

export function CollectionPage() {
  const { collectionId = '' } = useParams()
  const { t } = useTranslation('common')
  const query = useQuery({ queryKey: ['collection', collectionId], queryFn: () => api.collection(collectionId) })
  const missing = query.error instanceof ApiRequestError && query.error.code === 'COLLECTION_NOT_FOUND'
  if (missing && !query.data) return <div className="page-frame collections-empty"><FileText /><h1>{t('collections.notFound')}</h1><Button variant="outline" asChild><Link to="/collections">{t('action.detailBack', { target: t('nav.collections') })}</Link></Button></div>
  if (query.isError && !query.data) return <div className="page-frame"><Alert variant="destructive"><AlertDescription>{t('state.error')} · {query.error.message}<Button variant="outline" size="sm" onClick={() => query.refetch()}><RefreshCw />{t('action.retry')}</Button></AlertDescription></Alert></div>
  if (!query.data) return <div className="page-frame" aria-label={t('state.loading')}><Skeleton className="h-8 w-64" /><Skeleton className="mt-6 h-48 w-full" /></div>
  return <CollectionContent key={collectionId} requirement={query.data} readError={query.error} reload={() => query.refetch()} />
}

function CollectionContent({ requirement, reload, readError }: { requirement: CollectionDetail; reload: () => void; readError: Error | null }) {
  const { t, i18n } = useTranslation('common')
  const { user } = useAuth()
  const client = useQueryClient()
  const navigate = useNavigate()
  const canEdit = user.role === 'administrator' || user.role === 'engineer'
  const archived = requirement.status === 'archived'
  const [editing, setEditing] = useState<CollectionDetail | null>(null)
  const editTrigger = useRef<HTMLButtonElement | null>(null)
  const [confirmation, setConfirmation] = useState<{ type: 'delete' | 'archive'; revision: number } | null>(null)
  const [confirmName, setConfirmName] = useState('')
  const [params, setParams] = useSearchParams()
  const workspaceLink = useWorkspaceLink()
  const section = params.get('section') === 'sources' ? 'sources' : 'fields'
  const [goalExpanded, setGoalExpanded] = useState(false)
  const [addingSource, setAddingSource] = useState(false)
  const sourceTrigger = useRef<HTMLButtonElement | null>(null)
  const longGoal = requirement.intent.length > 180 || requirement.intent.includes('\n')
  const [fieldEditing, setFieldEditing] = useState(false)
  const [fieldSaving, setFieldSaving] = useState(false)
  const tabsRef = useRef<HTMLDivElement | null>(null)
  const blocker = useBlocker(({ currentLocation, nextLocation }) => fieldEditing && currentLocation.pathname !== nextLocation.pathname)
  const [notice, setNotice] = useState('')
  const invalidate = () => {
    client.invalidateQueries({ queryKey: ['collections'] })
    client.invalidateQueries({ queryKey: ['collectors'] })
    client.invalidateQueries({ queryKey: ['collector'] })
    client.invalidateQueries({ queryKey: ['collection', requirement.id] })
  }
  const update = useMutation({ mutationFn: (input: CollectionUpdateInput) => api.updateCollection(requirement.id, input), onSuccess: () => {
    invalidate(); setNotice('collections.saved'); setEditing(null); setConfirmation(null)
  } })
  const deletion = useMutation({ mutationFn: (revision: number) => api.deleteCollection(requirement.id, revision), onSuccess: () => {
    client.removeQueries({ queryKey: ['collection', requirement.id] })
    client.invalidateQueries({ queryKey: ['collections'] })
    navigate('/collections', { replace: true })
  } })
  const pending = update.isPending || deletion.isPending
  const error = update.error ?? deletion.error
  const reset = () => { update.reset(); deletion.reset(); setConfirmName('') }
  const errorNotice = error && <Alert variant="destructive"><AlertDescription>{error.message}
    {error instanceof ApiRequestError && ['COLLECTION_CONFLICT', 'COLLECTION_HAS_SOURCES', 'COLLECTION_ARCHIVED'].includes(error.code)
      && <Button variant="outline" size="sm" onClick={() => { setEditing(null); setConfirmation(null); reset(); reload() }}><RefreshCw />{t(editing ? 'collections.discardReload' : 'collections.reload')}</Button>}
  </AlertDescription></Alert>
  return <div className="page-frame collection-detail-page">
    <header className="collection-detail-header">
      <div className="requirement-heading"><div className="requirement-title-row"><span className={`requirement-lifecycle ${archived ? 'is-archived' : ''}`}>{archived ? <Archive size={13} /> : <Check size={13} />}{t(archived ? 'collections.archived' : 'collections.active')}</span>{requirement.activeVersion ? <span className="requirement-lifecycle" title={`Digest: ${requirement.activeVersion.outputContractDigest}`}><Check size={13} />v{requirement.activeVersion.versionNumber} ({t('collections.versionActive')})</span> : <span className="requirement-lifecycle is-archived">{t('collections.versionDraftOnly')}</span>}<h1>{requirement.name}</h1></div><div className="requirement-header-meta"><span>{t('collections.sourcePublication')} <strong>{requirement.publishedSourceCount} / {requirement.sourceCount}</strong></span><span>{t('fields.updatedAt')} <time dateTime={requirement.updatedAt}>{new Date(requirement.updatedAt).toLocaleString(i18n.resolvedLanguage)}</time></span></div></div>
      {canEdit && <div className="collection-detail-actions">
        {archived ? <Button variant="outline" disabled={pending} onClick={() => { reset(); update.mutate({ revision: requirement.revision, status: 'active' }) }}><ArchiveRestore />{t('collections.restore')}</Button>
          : <><Button ref={editTrigger} variant="outline" size="sm" disabled={pending || fieldEditing} onClick={() => { reset(); setNotice(''); setEditing(requirement) }}><Pencil />{t('collections.edit')}</Button>
            <Button ref={sourceTrigger} size="sm" disabled={pending || fieldEditing} onClick={() => setAddingSource(true)}><Plus />{t('collections.addSource')}</Button>
            <Button variant="ghost" size="icon-sm" title={t('collections.archive')} aria-label={t('collections.archive')} disabled={pending || fieldEditing} onClick={() => { reset(); setConfirmation({ type: 'archive', revision: requirement.revision }) }}><Archive /></Button></>}
        {requirement.sourceCount === 0 && !requirement.latestVersionNumber && <Button variant="ghost" size="icon-sm" title={t('collections.delete')} aria-label={t('collections.delete')} disabled={pending || fieldEditing} onClick={() => { reset(); setConfirmation({ type: 'delete', revision: requirement.revision }) }}><Trash2 /></Button>}
      </div>}
    </header>
    {archived && <Alert><AlertDescription>{t('collections.archivedNotice')}</AlertDescription></Alert>}
    {notice && <p role="status" className="requirement-save-success"><Check size={14} />{t(notice)}</p>}
    {readError && <Alert variant="destructive"><AlertDescription>{readError.message}<Button variant="outline" size="sm" onClick={reload}><RefreshCw />{t('action.retry')}</Button></AlertDescription></Alert>}
    {!editing && !confirmation && errorNotice}
    <section className={`requirement-goal-summary ${longGoal ? 'can-collapse' : ''} ${goalExpanded ? 'is-expanded' : ''}`} aria-label={t('collections.intent')}><span>{t('collections.intent')}</span><div><p id="requirement-goal">{requirement.intent}</p>{longGoal && <button className="requirement-goal-toggle" aria-expanded={goalExpanded} aria-controls="requirement-goal" onClick={() => setGoalExpanded(!goalExpanded)}>{t(goalExpanded ? 'collections.collapseGoal' : 'collections.expandGoal')}<ChevronDown size={13} /></button>}</div></section>
    <Tabs ref={tabsRef} value={section} onValueChange={value => { const next = new URLSearchParams(params); if (value === 'fields') next.delete('section'); else next.set('section', value); setParams(next) }} className="requirement-detail-tabs">
      <TabsList variant="line" aria-label={t('fields.detailSections')}><TabsTrigger value="fields">{t('fields.unified')}{fieldEditing && <span className="requirement-unsaved">{t('fields.unsaved')}</span>}</TabsTrigger><TabsTrigger value="sources">{t('collections.linkedSources')} · {requirement.sourceCount}</TabsTrigger></TabsList>
      <TabsContent value="fields" forceMount><CollectionFields requirement={requirement} canEdit={canEdit && !archived} canPublish={!archived && ['administrator', 'reviewer'].includes(user.role)} onEditingChange={setFieldEditing} onSavingChange={setFieldSaving} />{requirement.sourceCount === 0 && <p className="requirement-no-sources">{t('collections.noSources')}</p>}</TabsContent>
      <TabsContent value="sources">
    <section aria-labelledby="collection-sources-title">
      <h2 id="collection-sources-title" className="sr-only">{t('collections.linkedSources')}</h2>
      {requirement.sources.length === 0 ? <div className="collections-empty"><Layers3 /><h2>{t('collections.noSources')}</h2></div>
        : <div className="collections-table-scroll"><table className="collection-sources-table">
          <thead><tr><th scope="col">{t('nav.collectors')}</th><th scope="col">{t('collections.sourceStatus')}</th><th scope="col">{t('collections.versionAlignment')}</th><th scope="col">{t('fields.executionFields')}</th><th scope="col"><span className="sr-only">{t('collectors:management.edit')}</span></th></tr></thead>
          <tbody>{requirement.sources.map((source) => { const contract = requirement.sourceContracts?.find((item) => item.sourceId === source.id); const isAligned = contract?.isAligned ?? true; return <tr key={source.id}>
            <td><Link to={workspaceLink(`/collectors/${encodeURIComponent(source.id)}`)}><Layers3 size={16} /><strong>{source.name}</strong><ChevronRight size={14} /></Link><span className="collection-source-url">{source.sourceUrl}</span></td>
            <td>{source.lifecycle === 'archived' ? <ArchivedBadge /> : <StatusBadge status={source.status} />}</td>
            <td>{contract?.targetVersionNumber ? (isAligned ? <span className="requirement-lifecycle"><Check size={12} />v{contract.targetVersionNumber} ({t('collections.aligned')})</span> : <span className="requirement-lifecycle is-archived" title={`Source: ${contract.sourceVersion || 'unbound'}`}>{contract.sourceVersionNumber ? `v${contract.sourceVersionNumber}` : t('collections.unboundVersion')} → v{contract.targetVersionNumber} ({t('collections.outdated')})</span>) : <span className="requirement-lifecycle is-archived">{t('collections.versionDraftOnly')}</span>}<CollectionMigration source={source} targetVersionId={requirement.activeVersionId} canReview={!archived && ['administrator', 'reviewer'].includes(user.role)} /></td>
            <td>{!contract || contract.state === 'unavailable' ? <span className="requirement-field-diff">{t('fields.unknownCount')}</span> : contract.fields.length}</td>
            <td><CollectorManagement collector={source} /></td>
          </tr> })}</tbody>
        </table></div>}
    </section>
      </TabsContent>
    </Tabs>
    <Dialog open={blocker.state === 'blocked'} onOpenChange={open => { if (!open && !fieldSaving && blocker.state === 'blocked') blocker.reset() }}>
      <DialogContent onCloseAutoFocus={event => { event.preventDefault(); tabsRef.current?.querySelector<HTMLButtonElement>('[role="tab"][data-state="active"]')?.focus() }}><DialogHeader><DialogTitle>{t('fields.leaveTitle')}</DialogTitle><DialogDescription>{t('fields.leaveNotice')}</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" disabled={fieldSaving} onClick={() => blocker.state === 'blocked' && blocker.reset()}>{t('fields.keepEditing')}</Button><Button variant="destructive" disabled={fieldSaving} onClick={() => blocker.state === 'blocked' && blocker.proceed()}>{t('fields.discardLeave')}</Button></DialogFooter></DialogContent>
    </Dialog>
    {addingSource && <CollectionSourceDialog requirement={requirement} onClose={() => setAddingSource(false)} onRestoreFocus={() => sourceTrigger.current?.focus()} onCreated={() => { const next = new URLSearchParams(params); next.set('section', 'sources'); setParams(next, { replace: true }) }} />}
    <Dialog open={Boolean(editing)} onOpenChange={(open) => { if (!open && !pending) setEditing(null) }}>
      <DialogContent className="collection-edit-dialog" onCloseAutoFocus={event => { event.preventDefault(); editTrigger.current?.focus() }} onInteractOutside={(event) => event.preventDefault()}>
        <DialogHeader><DialogTitle>{t('collections.edit')}</DialogTitle><DialogDescription>{t('collections.editNotice')}</DialogDescription></DialogHeader>
        {errorNotice}
        {editing && <CollectionForm initial={editing} pending={pending} onCancel={() => setEditing(null)} onSave={(input) => update.mutate({ ...input, revision: editing.revision })} />}
      </DialogContent>
    </Dialog>
    <Dialog open={Boolean(confirmation)} onOpenChange={(open) => { if (!open && !pending) setConfirmation(null) }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t(confirmation?.type === 'delete' ? 'collections.delete' : 'collections.archive')}</DialogTitle><DialogDescription>{t(confirmation?.type === 'delete' ? 'collections.deleteNotice' : 'collections.archiveNotice', { name: requirement.name })}</DialogDescription></DialogHeader>
        {errorNotice}
        {confirmation?.type === 'delete' && <div className="field-group"><label htmlFor="confirm-requirement-name">{t('collections.confirmName')}</label><Input id="confirm-requirement-name" value={confirmName} onChange={(event) => setConfirmName(event.target.value)} disabled={pending} /></div>}
        <DialogFooter><Button variant="outline" disabled={pending} onClick={() => setConfirmation(null)}>{t('action.cancel')}</Button><Button variant={confirmation?.type === 'delete' ? 'destructive' : 'default'} disabled={pending || (confirmation?.type === 'delete' && confirmName !== requirement.name)} onClick={() => {
          if (!confirmation) return
          if (confirmation.type === 'delete') deletion.mutate(confirmation.revision)
          else update.mutate({ revision: confirmation.revision, status: 'archived' })
        }}>{t(pending ? 'collections.saving' : 'action.confirm')}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
}
