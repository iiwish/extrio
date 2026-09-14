import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Braces, Check, ChevronRight, Copy, History, KeyRound, Pencil, Plus, Save, ShieldCheck, Trash2, Undo2 } from 'lucide-react'
import { api, ApiRequestError } from '@/api/client'
import type { CollectionDetail, CollectionField, SourceFieldContract } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { CollectionFieldTools } from './collection-field-tools'

const fieldTypes: CollectionField['type'][] = ['string', 'number', 'integer', 'boolean', 'date', 'datetime', 'url', 'html', 'object', 'array']
const blankField = (): CollectionField => ({ key: '', label: '', type: 'string', required: false, identity: false, fingerprint: true, description: '' })
const sameField = (a: CollectionField, b: CollectionField) => ['type', 'required', 'identity', 'fingerprint'].every((key) => a[key as keyof CollectionField] === b[key as keyof CollectionField])

export function mergeSourceFields(contracts: SourceFieldContract[]): CollectionField[] {
  const fields = new Map<string, CollectionField>()
  for (const source of [...contracts].sort((a, b) => Number(b.state === 'published') - Number(a.state === 'published'))) {
    for (const field of source.fields) if (!fields.has(field.key)) fields.set(field.key, field)
  }
  return [...fields.values()]
}

export function CollectionFields({ requirement, canEdit, canPublish = false, onEditingChange, onSavingChange }: { requirement: CollectionDetail; canEdit: boolean; canPublish?: boolean; onEditingChange?: (editing: boolean) => void; onSavingChange?: (saving: boolean) => void }) {
  const { t } = useTranslation('common')
  const labelFor = (field: CollectionField) => field.label === field.key ? t(`fields.names.${field.key}`, { defaultValue: field.label }) : field.label
  const client = useQueryClient()
  const contracts = requirement.sourceContracts ?? []
  const merged = mergeSourceFields(contracts)
  const [inspecting, setInspecting] = useState<CollectionField | null>(null)
  const saved = requirement.fieldDraft
  const publishedVersion = useQuery({
    queryKey: ['collectionVersion', requirement.id, requirement.activeVersion?.id],
    queryFn: () => api.collectionVersion(requirement.id, requirement.activeVersion!.id),
    enabled: Boolean(requirement.activeVersion?.id),
    staleTime: Infinity,
  })
  const [draft, setDraft] = useState<{ fields: CollectionField[]; revision: number } | null>(null)
  const [fieldEdit, setFieldEdit] = useState<{ value: CollectionField; index: number } | null>(null)
  const [removed, setRemoved] = useState<{ value: CollectionField; index: number } | null>(null)
  const [savedNotice, setSavedNotice] = useState(false)
  const dialogTrigger = useRef<HTMLButtonElement | null>(null)
  const editTrigger = useRef<HTMLButtonElement | null>(null)
  const restoreFocus = (event: Event) => { event.preventDefault(); const target = dialogTrigger.current?.isConnected ? dialogTrigger.current : editTrigger.current; target?.focus() }
  const mutation = useMutation({ mutationFn: (value: NonNullable<typeof draft>) => api.updateCollection(requirement.id, { revision: value.revision, fieldDraft: { fields: value.fields } }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['collection', requirement.id] })
      client.invalidateQueries({ queryKey: ['collections'] })
      setDraft(null); setRemoved(null); setSavedNotice(true)
    } })
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishSnapshot, setPublishSnapshot] = useState<{ revision: number; fields: CollectionField[]; number: number } | null>(null)
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false)
  const [publishNotice, setPublishNotice] = useState<string | null>(null)
  const publishMutation = useMutation({
    mutationFn: (note?: string) =>
      api.publishCollectionVersion(requirement.id, {
        revision: publishSnapshot!.revision,
        note: note?.trim() || undefined,
      }),
    onSuccess: async (data) => {
      await client.invalidateQueries({ queryKey: ['collection', requirement.id] })
      await client.invalidateQueries({ queryKey: ['collectionVersions', requirement.id] })
      client.invalidateQueries({ queryKey: ['collections'] })
      setPublishOpen(false)
      setSavedNotice(false)
      setPublishNotice(t('collections.publishedSuccess', { version: data.versionNumber }))
    },
  })
  const editingDraft = Boolean(draft)
  useEffect(() => { onEditingChange?.(editingDraft) }, [editingDraft, onEditingChange])
  useEffect(() => { onSavingChange?.(mutation.isPending || publishMutation.isPending) }, [mutation.isPending, publishMutation.isPending, onSavingChange])
  useEffect(() => {
    if (!draft) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [draft])
  const fields = draft?.fields ?? saved?.fields ?? merged
  const publishedFields = publishedVersion.data?.fields
  const matchesPublished = !draft && Boolean(saved && publishedFields && saved.fields.length === publishedFields.length && saved.fields.every((field, index) =>
    sameField(field, publishedFields[index]) && field.key === publishedFields[index].key && field.label === publishedFields[index].label && field.description === publishedFields[index].description))
  const hasUnpublishedDraft = Boolean(draft || (saved && (!requirement.activeVersion || publishedVersion.isSuccess))) && !matchesPublished
  const start = () => { mutation.reset(); setSavedNotice(false); setDraft({ fields: structuredClone(fields).map((field) => ({ ...field, label: labelFor(field), required: field.required || field.identity })), revision: requirement.revision }) }
  const sourceExtras = saved ? merged.filter((field) => !saved.fields.some((item) => item.key === field.key)) : []
  const [showExtras, setShowExtras] = useState(false)
  const displayedFields = !draft && showExtras ? [...fields, ...sourceExtras] : fields
  const coverage = (field: CollectionField) => contracts.filter((source) => source.fields.some((item) => item.key === field.key))
  const hasDifference = (field: CollectionField) => coverage(field).some((source) => source.fields.some((item) => item.key === field.key && !sameField(item, field)))
  const [importSourceOpen, setImportSourceOpen] = useState(false)
  const availableContracts = contracts.filter((source) => source.fields.length > 0)
  const handleApplySource = (importMode: 'replace' | 'merge', source: SourceFieldContract) => {
    mutation.reset()
    setSavedNotice(false)
    const formatted = source.fields.map((field) => ({
      ...field,
      label: labelFor(field),
      required: field.required || field.identity,
    }))
    if (importMode === 'replace') {
      setDraft({ fields: formatted.slice(0, 100), revision: requirement.revision })
    } else {
      const current = draft?.fields ?? saved?.fields ?? []
      const existingKeys = new Set(current.map((field) => field.key))
      const additions = formatted.filter((field) => !existingKeys.has(field.key))
      setDraft({ fields: [...current, ...additions].slice(0, 100), revision: requirement.revision })
    }
  }

  return <section className="requirement-fields" aria-label={t('fields.unified')}>
    <div className={`requirement-fields-toolbar ${draft ? 'is-editing' : ''}`}>
      <div className="requirement-fields-heading">
        <span>{t('fields.count', { count: displayedFields.length })}</span>
        <span className={`requirement-field-state ${hasUnpublishedDraft ? 'is-draft' : ''}`}>{t(matchesPublished ? 'fields.publishedDefinition' : hasUnpublishedDraft ? 'fields.draft' : saved ? 'fields.requirements' : 'fields.sourceSummary')}</span>
        {requirement.activeVersion ? (
          <span className="requirement-lifecycle" title={`Digest: ${requirement.activeVersion.outputContractDigest}`}>
            <Check size={12} />v{requirement.activeVersion.versionNumber} ({t('collections.versionActive')})
          </span>
        ) : (
          <span className="requirement-lifecycle is-archived">{t('collections.versionDraftOnly')}</span>
        )}
        {draft && <span className="requirement-unsaved">{t('fields.unsaved')}</span>}
      </div>
      <div className="requirement-field-actions">
        {canEdit && <CollectionFieldTools requirement={requirement} disabled={Boolean(draft) || mutation.isPending || publishMutation.isPending} />}
        <Button size="sm" variant="outline" onClick={(event) => { dialogTrigger.current = event.currentTarget; setVersionHistoryOpen(true) }}>
          <History size={14} />{t('collections.versionHistory')}
          {requirement.activeVersion && ` (v${requirement.activeVersion.versionNumber})`}
        </Button>
        {canEdit && availableContracts.length > 0 && (
          <Button size="sm" variant="outline" disabled={Boolean(draft) || mutation.isPending || publishMutation.isPending} onClick={() => setImportSourceOpen(true)}>
            <Copy size={14} />{t('fields.generateFromSource')}
          </Button>
        )}
        {canEdit && !draft && (
          <>
            <Button ref={editTrigger} size="sm" variant="outline" onClick={start}><Pencil size={14} />{t('fields.edit')}</Button>
          </>
        )}
        {canPublish && !draft && Boolean(saved?.fields.length) && <Button size="sm" disabled={publishMutation.isPending} onClick={(event) => { dialogTrigger.current = event.currentTarget; publishMutation.reset(); setPublishSnapshot({ revision: requirement.revision, fields: structuredClone(saved!.fields), number: (requirement.latestVersionNumber ?? 0) + 1 }); setPublishOpen(true) }}><ShieldCheck size={14} />{t('collections.publishVersion')}</Button>}
        {draft && <>
          {removed && <Button size="sm" variant="ghost" disabled={mutation.isPending || draft.fields.some((field) => field.key === removed.value.key)} onClick={() => { const next = [...draft.fields]; next.splice(Math.min(removed.index, next.length), 0, removed.value); setDraft({ ...draft, fields: next }); setRemoved(null) }}><Undo2 size={14} />{t('fields.undoDelete')}</Button>}
          <Button ref={editTrigger} size="sm" variant="outline" disabled={mutation.isPending || draft.fields.length >= 100} onClick={event => { dialogTrigger.current = event.currentTarget; setFieldEdit({ value: blankField(), index: -1 }) }}><Plus size={14} />{t('fields.add')}</Button>
          <Button size="sm" variant="ghost" disabled={mutation.isPending} onClick={() => { setDraft(null); setRemoved(null); mutation.reset() }}>{t('action.cancel')}</Button>
          <Button size="sm" disabled={mutation.isPending || !canEdit} onClick={() => mutation.mutate(draft)}><Save size={14} />{t(mutation.isPending ? 'collections.saving' : 'fields.saveDraft')}</Button>
        </>}
      </div>
    </div>
    {hasUnpublishedDraft && <p className="requirement-field-notice">{t('fields.compactDraftNotice')}</p>}
    {publishedVersion.error && <Alert variant="destructive"><AlertDescription>{publishedVersion.error.message}</AlertDescription></Alert>}
    {savedNotice && !matchesPublished && <p role="status" className="requirement-save-success"><Check size={14} />{t('fields.saved')}</p>}
    {publishNotice && <p role="status" className="requirement-save-success"><Check size={14} />{publishNotice}</p>}
    {publishMutation.error && <Alert variant="destructive"><AlertDescription>{publishMutation.error.message}</AlertDescription></Alert>}
    {mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error.message}
      {mutation.error instanceof ApiRequestError && mutation.error.code === 'COLLECTION_CONFLICT' && <Button variant="outline" size="sm" onClick={async () => { await client.invalidateQueries({ queryKey: ['collection', requirement.id] }); setDraft(null); mutation.reset() }}>{t('fields.discardReload')}</Button>}
    </AlertDescription></Alert>}
    {contracts.some((source) => source.state === 'unavailable') && <Alert variant="destructive"><AlertDescription>{t('fields.unavailableNotice')}</AlertDescription></Alert>}
    {displayedFields.length ? <div className="requirement-fields-scroll"><table className="requirement-fields-table requirement-fields-unified">
      <colgroup><col className="requirement-col-name" /><col className="requirement-col-type" /><col className="requirement-col-rules" /><col className="requirement-col-coverage" />{draft && <col className="requirement-col-actions" />}</colgroup>
      <thead><tr><th scope="col">{t('fields.label')}</th><th scope="col">{t('fields.type')}</th><th scope="col">{t('fields.rules')}</th><th scope="col">{t('fields.coverage')}</th>{draft && <th scope="col"><span className="sr-only">{t('fields.actions')}</span></th>}</tr></thead>
      <tbody>{displayedFields.map((field, index) => <tr key={field.key}>
        <td><span className="requirement-field-name">{labelFor(field)}</span><code className="requirement-field-key">{field.key}</code>{field.description && <p className="requirement-field-description">{field.description}</p>}{saved && !saved.fields.some((item) => item.key === field.key) && !draft && <small className="requirement-field-extra">{t('fields.extra')}</small>}</td><td>{!saved && !draft && hasDifference(field) && coverage(field).some((source) => source.fields.find((item) => item.key === field.key)?.type !== field.type) ? t('fields.varies') : t(`fields.types.${field.type}`, { defaultValue: field.type })}</td>
        <td>{!saved && !draft && hasDifference(field) ? <span className="requirement-field-diff">{t('fields.varies')}</span> : <div className="requirement-field-rules">{field.required && <span>{t('fields.required')}</span>}{field.identity && <span title={t('fields.identity')}><KeyRound size={12} />{t('fields.identity')}</span>}{field.fingerprint && <span>{t('fields.fingerprint')}</span>}{!field.required && !field.identity && !field.fingerprint && <span>{t('fields.optional')}</span>}</div>}</td>
        <td><button type="button" className="requirement-coverage" aria-label={t('fields.inspectNamed', { name: labelFor(field) })} onClick={event => { dialogTrigger.current = event.currentTarget; setInspecting(field) }}><span>{coverage(field).length} / {requirement.sourceCount}</span>{hasDifference(field) && <span className="requirement-field-diff">{t('fields.difference')}</span>}<ChevronRight size={14} /></button></td>
        {draft && <td><div className="requirement-field-actions"><Button variant="ghost" size="icon-sm" title={t('fields.editNamed', { name: field.label })} aria-label={t('fields.editNamed', { name: field.label })} disabled={mutation.isPending} onClick={event => { dialogTrigger.current = event.currentTarget; setFieldEdit({ value: { ...field }, index }) }}><Pencil /></Button><Button variant="ghost" size="icon-sm" title={t('fields.deleteNamed', { name: field.label })} aria-label={t('fields.deleteNamed', { name: field.label })} disabled={mutation.isPending} onClick={() => { setRemoved({ value: field, index }); setDraft({ ...draft, fields: draft.fields.filter((_, i) => i !== index) }) }}><Trash2 /></Button></div></td>}
      </tr>)}</tbody>
    </table></div> : <div className="requirement-fields-empty"><Braces size={26} /><h3>{t('fields.noFields')}</h3>{canEdit && <div className="requirement-field-actions">{availableContracts.length > 0 && <Button variant="outline" onClick={() => setImportSourceOpen(true)}><Copy />{t('fields.generateFromSource')}</Button>}{!draft && <Button variant="outline" onClick={() => { start(); setFieldEdit({ value: blankField(), index: -1 }) }}><Plus />{t('fields.add')}</Button>}</div>}</div>}
    {!draft && sourceExtras.length > 0 && <Button variant="ghost" size="sm" className="requirement-extra-toggle" onClick={() => setShowExtras(!showExtras)}>{t(showExtras ? 'fields.hideExtras' : 'fields.showExtras', { count: sourceExtras.length })}</Button>}
    {draft && contracts.some((item) => item.fields.length) && <details className="requirement-import-fields"><summary><Copy size={14} />{t('fields.importSource')}</summary><div>{contracts.filter((item) => item.fields.length).map((item) => <Button key={item.sourceId} size="sm" variant="outline" disabled={mutation.isPending} onClick={() => {
      const keys = new Set(draft.fields.map((field) => field.key))
      const additions = item.fields.filter((field) => !keys.has(field.key)).map((field) => ({ ...field, required: field.required || field.identity }))
      setDraft({ ...draft, fields: [...draft.fields, ...additions].slice(0, 100) })
    }}><Plus />{item.sourceName}</Button>)}</div></details>}
    <ImportSourceDialog open={importSourceOpen} onOpenChange={setImportSourceOpen} contracts={contracts} onApply={handleApplySource} />
    <Dialog open={Boolean(inspecting)} onOpenChange={(open) => { if (!open) setInspecting(null) }}><DialogContent className="requirement-source-dialog" onCloseAutoFocus={restoreFocus}><DialogHeader><DialogTitle>{inspecting && labelFor(inspecting)} · {t('fields.coverage')}</DialogTitle><DialogDescription>{inspecting?.key}</DialogDescription></DialogHeader>
      {contracts.length === 0 && <p>{t('collections.noSources')}</p>}
      {inspecting && contracts.map((source) => { const actual = source.fields.find((field) => field.key === inspecting.key); return <div key={source.sourceId} className="requirement-source-evidence"><div className="requirement-source-evidence-title"><Link to={`/collectors/${encodeURIComponent(source.sourceId)}`}>{source.sourceName}</Link><span>{t(`fields.${source.state}`)}</span></div>
        {actual ? <p className="requirement-source-rule">{t(`fields.types.${actual.type}`)} · {t(actual.required ? 'fields.required' : 'fields.optional')}{actual.identity && ` · ${t('fields.identity')}`}{actual.fingerprint && ` · ${t('fields.fingerprint')}`}</p> : <p className="requirement-field-diff">{t(source.state === 'unavailable' ? 'fields.unavailable' : source.state === 'empty' ? 'fields.empty' : 'fields.notCollected')}</p>}
        {actual && <ContractEvidence source={source} />}
      </div> })}
    </DialogContent></Dialog>
    <Dialog open={Boolean(fieldEdit)} onOpenChange={(open) => { if (!open) setFieldEdit(null) }}>
      <DialogContent className="requirement-field-dialog" onCloseAutoFocus={restoreFocus} onInteractOutside={(event) => event.preventDefault()}><DialogHeader><DialogTitle>{t(fieldEdit?.index === -1 ? 'fields.add' : 'fields.editOne')}</DialogTitle><DialogDescription>{t('fields.fieldNotice')}</DialogDescription></DialogHeader>
        {fieldEdit && <FieldForm key={`${fieldEdit.index}-${fieldEdit.value.key}`} field={fieldEdit.value} otherKeys={(draft?.fields ?? []).filter((_, index) => index !== fieldEdit.index).map((field) => field.key)} onCancel={() => setFieldEdit(null)} onSave={(field) => { if (!draft) return; const next = [...draft.fields]; if (fieldEdit.index === -1) next.push(field); else next[fieldEdit.index] = field; setDraft({ ...draft, fields: next }); setFieldEdit(null) }} />}
      </DialogContent>
    </Dialog>
    <PublishVersionDialog
      open={publishOpen}
      restoreFocus={restoreFocus}
      onOpenChange={setPublishOpen}
      nextVersion={publishSnapshot?.number ?? 1}
      fields={publishSnapshot?.fields ?? []}
      pending={publishMutation.isPending}
      error={publishMutation.error}
      onPublish={(note) => publishMutation.mutate(note)}
    />
    <VersionHistoryDialog
      open={versionHistoryOpen}
      restoreFocus={restoreFocus}
      onOpenChange={setVersionHistoryOpen}
      collectionId={requirement.id}
      activeVersionId={requirement.activeVersionId}
    />
  </section>
}

function ImportSourceDialog({
  open,
  onOpenChange,
  contracts,
  onApply,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  contracts: SourceFieldContract[]
  onApply: (mode: 'replace' | 'merge', source: SourceFieldContract) => void
}) {
  const { t } = useTranslation('common')
  const available = contracts.filter((c) => c.fields.length > 0)
  const [selectedSourceId, setSelectedSourceId] = useState<string>('')
  const [mode, setMode] = useState<'replace' | 'merge'>('replace')

  const effectiveSourceId = selectedSourceId || available[0]?.sourceId || ''
  const selectedSource = available.find((c) => c.sourceId === effectiveSourceId) ?? available[0]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="requirement-source-dialog max-w-md">
        <DialogHeader>
          <DialogTitle>{t('fields.generateFromSource')}</DialogTitle>
          <DialogDescription>{t('fields.generateFromSourceDesc')}</DialogDescription>
        </DialogHeader>
        {available.length === 0 ? (
          <p>{t('collections.noSources')}</p>
        ) : (
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">{t('fields.selectSource')}</label>
              {available.length === 1 ? (
                <div className="rounded border px-3 py-2 text-sm bg-muted/30">
                  <strong>{selectedSource?.sourceName}</strong>
                  <span className="ml-2 text-muted-foreground">({t('fields.count', { count: selectedSource?.fields.length })})</span>
                </div>
              ) : (
                <Select value={effectiveSourceId} onValueChange={setSelectedSourceId}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {available.map((c) => (
                      <SelectItem key={c.sourceId} value={c.sourceId}>
                        {c.sourceName} ({t('fields.count', { count: c.fields.length })})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">{t('fields.syncMode')}</label>
              <div className="space-y-2 rounded border p-3">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="sync-mode"
                    className="mt-1"
                    checked={mode === 'replace'}
                    onChange={() => setMode('replace')}
                  />
                  <div>
                    <div className="text-sm font-medium">{t('fields.replaceWithSource')}</div>
                    <div className="text-xs text-muted-foreground">{t('fields.replaceWithSourceDesc')}</div>
                  </div>
                </label>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="sync-mode"
                    className="mt-1"
                    checked={mode === 'merge'}
                    onChange={() => setMode('merge')}
                  />
                  <div>
                    <div className="text-sm font-medium">{t('fields.mergeWithSource')}</div>
                    <div className="text-xs text-muted-foreground">{t('fields.mergeWithSourceDesc')}</div>
                  </div>
                </label>
              </div>
            </div>

            {selectedSource && (
              <div className="rounded bg-muted/50 p-2.5 text-xs text-muted-foreground">
                {t('g2.fieldsIncluded', { fields: selectedSource.fields.map((f) => f.label || f.key).join(', ') })}
              </div>
            )}
          </div>
        )}
        <div className="requirement-field-actions justify-end">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('action.cancel')}
          </Button>
          <Button
            disabled={!selectedSource}
            onClick={() => {
              if (selectedSource) {
                onApply(mode, selectedSource)
                onOpenChange(false)
              }
            }}
          >
            <Check />
            {t('fields.applySourceFields')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ContractEvidence({ source }: { source: SourceFieldContract }) {
  const { t } = useTranslation('common')
  return <><dl className="requirement-quality">{['requiredFieldCompleteness', 'maxItemErrorRatio', 'emptyResultPolicy'].map((key) => {
    const value = source.quality[key]
    if (typeof value !== 'number' && typeof value !== 'string') return null
    return <div key={key}><dt>{t(`fields.quality.${key}`)}</dt><dd>{typeof value === 'number' ? `${Math.round(value * 100)}%` : t(`fields.quality.${value}`, { defaultValue: value })}</dd></div>
  })}</dl><details className="requirement-contract-evidence"><summary>{t('fields.schema')}</summary><pre>{JSON.stringify({ ruleVersion: source.ruleVersion, schema: source.schema, quality: source.quality }, null, 2)}</pre></details></>
}

function FieldForm({ field, otherKeys, onSave, onCancel }: { field: CollectionField; otherKeys: string[]; onSave: (field: CollectionField) => void; onCancel: () => void }) {
  const { t } = useTranslation('common')
  const [value, setValue] = useState(field)
  const validKey = /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(value.key) && !otherKeys.includes(value.key)
  return <form className="requirement-field-form" onSubmit={(event) => { event.preventDefault(); if (validKey && value.label.trim()) onSave({ ...value, label: value.label.trim(), description: value.description.trim() }) }}>
    <div className="requirement-field-form-grid"><div className="field-group"><label htmlFor="field-label">{t('fields.label')}</label><Input id="field-label" autoFocus required maxLength={100} value={value.label} onChange={(event) => setValue({ ...value, label: event.target.value })} /></div>
      <div className="field-group"><label htmlFor="field-key">{t('fields.key')}</label><Input id="field-key" required maxLength={64} aria-invalid={Boolean(value.key) && !validKey} value={value.key} onChange={(event) => setValue({ ...value, key: event.target.value })} />{value.key && !validKey && <span className="requirement-field-error">{t('fields.invalidKey')}</span>}</div></div>
    <div className="field-group"><label htmlFor="field-type">{t('fields.type')}</label><Select value={value.type} onValueChange={(type) => setValue({ ...value, type: type as CollectionField['type'] })}><SelectTrigger id="field-type"><SelectValue /></SelectTrigger><SelectContent>{fieldTypes.map((type) => <SelectItem key={type} value={type}>{t(`fields.types.${type}`)}</SelectItem>)}</SelectContent></Select></div>
    <div className="requirement-field-checks">{(['required', 'identity', 'fingerprint'] as const).map((key) => <label key={key}><Checkbox checked={value[key]} onCheckedChange={(checked) => setValue({ ...value, [key]: Boolean(checked), ...(key === 'identity' && checked ? { required: true } : {}), ...(key === 'required' && !checked ? { identity: false } : {}) })} />{t(`fields.${key}`)}</label>)}</div>
    <div className="field-group"><label htmlFor="field-description">{t('fields.description')}</label><Textarea id="field-description" maxLength={2000} value={value.description} onChange={(event) => setValue({ ...value, description: event.target.value })} /></div>
    <div className="requirement-field-actions justify-end"><Button type="button" variant="outline" onClick={onCancel}>{t('action.cancel')}</Button><Button disabled={!validKey || !value.label.trim()} type="submit"><Check />{t('fields.apply')}</Button></div>
  </form>
}

function PublishVersionDialog({
  restoreFocus,
  open,
  onOpenChange,
  nextVersion,
  fields,
  pending,
  error,
  onPublish,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  restoreFocus: (event: Event) => void
  nextVersion: number
  fields: CollectionField[]
  pending: boolean
  error: Error | null
  onPublish: (note?: string) => void
}) {
  const { t } = useTranslation('common')
  const [note, setNote] = useState('')
  const identityFields = fields.filter((f) => f.identity)
  const fingerprints = fields.filter((f) => f.fingerprint)
  const valid = identityFields.length > 0 && identityFields.length <= 16 && fingerprints.length > 0 && fingerprints.length <= 64

  return (
    <Dialog open={open} onOpenChange={(value) => { if (!pending) onOpenChange(value) }}>
      <DialogContent onCloseAutoFocus={restoreFocus} className="requirement-source-dialog max-w-md">
        <DialogHeader>
          <DialogTitle>{t('collections.publishVersion')}</DialogTitle>
          <DialogDescription>{t('collections.publishVersionNotice')}</DialogDescription>
        </DialogHeader>
        {error && <Alert variant="destructive"><AlertDescription>{error.message}</AlertDescription></Alert>}
        {!valid && <Alert variant="destructive"><AlertDescription>{t('g2.fingerprintGate')}</AlertDescription></Alert>}
        <div className="space-y-4 py-2 text-sm">
          <div className="rounded border bg-muted/30 p-3 space-y-1.5">
            <div className="flex justify-between font-medium">
              <span>{t('collections.versionNumber', { version: nextVersion })}</span>
              <span>{t('fields.count', { count: fields.length })}</span>
            </div>
            <div className="text-xs text-muted-foreground">
              {t('fields.identity')}: {identityFields.map((f) => f.label || f.key).join('、') || t('fields.optional')}
            </div>
          </div>
          <div className="field-group">
            <label htmlFor="publish-version-note">{t('collections.versionNote')}</label>
            <Textarea
              id="publish-version-note"
              placeholder={t('collections.versionNotePlaceholder')}
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={pending}
            />
          </div>
        </div>
        <div className="requirement-field-actions justify-end">
          <Button type="button" variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t('action.cancel')}
          </Button>
          <Button disabled={pending || !valid} onClick={() => onPublish(note)}>
            <Check size={14} />
            {t(pending ? 'collections.publishing' : 'collections.publishVersion')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function VersionHistoryDialog({
  restoreFocus,
  open,
  onOpenChange,
  collectionId,
  activeVersionId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  collectionId: string
  restoreFocus: (event: Event) => void
  activeVersionId?: string | null
}) {
  const { t, i18n } = useTranslation('common')
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['collectionVersions', collectionId],
    queryFn: () => api.collectionVersions(collectionId),
    enabled: open,
  })
  const versions = data?.items ?? []
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent onCloseAutoFocus={restoreFocus} className="requirement-source-dialog max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('collections.historyTitle')}</DialogTitle>
          <DialogDescription>{t('collections.historyDesc')}</DialogDescription>
        </DialogHeader>
        {error ? <Alert variant="destructive"><AlertDescription>{t('g2.historyError')}: {error.message}<Button variant="outline" onClick={() => refetch()}>{t('action.retry')}</Button></AlertDescription></Alert> : isLoading ? (
          <div className="py-6 text-center text-sm text-muted-foreground">{t('state.loading')}</div>
        ) : versions.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">{t('collections.noVersions')}</div>
        ) : (
          <div className="space-y-3 py-2">
            {versions.map((ver) => {
              const isActive = ver.id === activeVersionId
              const isExpanded = expandedId === ver.id
              return (
                <div key={ver.id} className="rounded border bg-card p-3 space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <strong className="text-base">v{ver.versionNumber}</strong>
                      {isActive && (
                        <span className="requirement-lifecycle">
                          <Check size={12} />
                          {t('collections.versionActive')}
                        </span>
                      )}
                      <span className="text-xs text-muted-foreground font-mono">
                        {ver.outputContractDigest.slice(0, 16)}...
                      </span>
                    </div>
                    <time className="text-xs text-muted-foreground" dateTime={ver.publishedAt}>
                      {new Date(ver.publishedAt).toLocaleString(i18n.resolvedLanguage)}
                    </time>
                  </div>
                  {ver.note && <p className="text-xs text-muted-foreground">{ver.note}</p>}
                  <div className="flex items-center justify-between text-xs pt-1 border-t">
                    <span className="text-muted-foreground">{t('collections.versionPublishedBy', { user: ver.publishedBy })}</span>
                    <button
                      type="button"
                      className="text-primary hover:underline font-medium"
                      onClick={() => setExpandedId(isExpanded ? null : ver.id)}
                    >
                      {t('collections.frozenFields', { count: ver.fields.length })} {isExpanded ? '▲' : '▼'}
                    </button>
                  </div>
                  {isExpanded && (
                    <div className="rounded bg-muted/40 p-2.5 mt-2 space-y-1.5 text-xs">
                      <div className="font-medium text-foreground">{t('fields.unified')}:</div>
                      <div className="grid grid-cols-2 gap-1 font-mono">
                        {ver.fields.map((f) => (
                          <div key={f.key} className="flex items-center gap-1">
                            <span className="text-foreground">{f.label || f.key}</span>
                            <span className="text-muted-foreground">({f.type})</span>
                            {f.identity && <KeyRound size={10} className="text-primary" />}
                          </div>
                        ))}
                      </div>
                      <details className="requirement-contract-evidence"><summary>{t('g2.versionContract')}</summary><pre>{JSON.stringify(ver, null, 2)}</pre></details>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
