import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Check, LayoutTemplate, LoaderCircle, RefreshCw, Sparkles } from 'lucide-react'
import { api } from '@/api/client'
import type { CollectionDetail, CollectionField } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

export function FieldContractValue({ field }: { field: CollectionField | null | undefined }) {
  const { t } = useTranslation('common')
  if (!field) return <span className="text-muted-foreground">{t('g2.noField')}</span>
  return <div className="g2-field-value"><strong>{field.label}</strong><span>{t(`fields.types.${field.type}`)} · {t(field.required ? 'fields.required' : 'fields.optional')}{field.identity && ` · ${t('fields.identity')}`}{field.fingerprint && ` · ${t('fields.fingerprint')}`}</span>{field.description && <small>{field.description}</small>}</div>
}

export function CollectionFieldTools({ requirement, disabled }: { requirement: CollectionDetail; disabled: boolean }) {
  const { t } = useTranslation('common')
  const [dialog, setDialog] = useState<{ type: 'template' | 'ai'; revision: number } | null>(null)
  const trigger = useRef<HTMLButtonElement | null>(null)
  return <>
    <Button size="sm" variant="outline" disabled={disabled} onClick={(event) => { trigger.current = event.currentTarget; setDialog({ type: 'template', revision: requirement.revision }) }}><LayoutTemplate />{t('g2.templates')}</Button>
    <Button size="sm" variant="outline" disabled={disabled} onClick={(event) => { trigger.current = event.currentTarget; setDialog({ type: 'ai', revision: requirement.revision }) }}><Sparkles />{t('g2.ai')}</Button>
    {dialog && <FieldToolsDialog key={dialog.type} requirement={requirement} mode={dialog.type} revision={dialog.revision} onClose={() => setDialog(null)} restoreFocus={() => trigger.current?.focus()} />}
  </>
}

function FieldToolsDialog({ requirement, mode, revision, onClose, restoreFocus }: { requirement: CollectionDetail; mode: 'template' | 'ai'; revision: number; onClose: () => void; restoreFocus: () => void }) {
  const { t, i18n } = useTranslation('common')
  const client = useQueryClient()
  const [templateId, setTemplateId] = useState('')
  const [suggestionId, setSuggestionId] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const templates = useQuery({ queryKey: ['collectionTemplates'], queryFn: api.collectionTemplates, enabled: mode === 'template' })
  const suggestions = useQuery({ queryKey: ['fieldSuggestions', requirement.id], queryFn: () => api.fieldSuggestions(requirement.id), enabled: mode === 'ai', refetchInterval: (query) => query.state.data?.some((item) => ['queued', 'running'].includes(item.status)) ? 1500 : false })
  const template = templates.data?.find((item) => item.id === templateId) ?? templates.data?.[0]
  const suggestion = suggestions.data?.find((item) => item.id === suggestionId) ?? suggestions.data?.[0]
  const fields = mode === 'template' ? template?.fields ?? [] : suggestion?.fields ?? []
  const active = suggestions.data?.some((item) => ['queued', 'running'].includes(item.status)) ?? false
  const invalidate = async () => {
    await client.invalidateQueries({ queryKey: ['collection', requirement.id] })
    await client.invalidateQueries({ queryKey: ['fieldSuggestions', requirement.id] })
    client.invalidateQueries({ queryKey: ['collections'] })
  }
  const generate = useMutation({ mutationFn: () => api.startFieldSuggestion(requirement.id, { revision: requirement.revision }), onSuccess: async (value) => {
    setSuggestionId(value.id); setSelected([])
    await client.invalidateQueries({ queryKey: ['fieldSuggestions', requirement.id] })
  } })
  const apply = useMutation({ mutationFn: async () => {
    if (mode === 'template' && template) return api.applyCollectionTemplate(requirement.id, { revision, templateId: template.id })
    if (suggestion) return api.applyFieldSuggestion(requirement.id, suggestion.id, { revision: suggestion.baseRevision, selectedKeys: selected })
    throw new Error(t('g2.emptySuggestions'))
  }, onSuccess: async () => { await invalidate(); onClose() } })
  const query = mode === 'template' ? templates : suggestions
  const error = apply.error ?? generate.error ?? query.error
  const stale = mode === 'template' ? revision !== requirement.revision : Boolean(suggestion && suggestion.baseRevision !== requirement.revision && !suggestion.appliedAt)
  const applyDisabled = apply.isPending || stale || (mode === 'template' ? !template : !suggestion || suggestion.status !== 'succeeded' || Boolean(suggestion.appliedAt) || selected.length === 0)
  return <Dialog open onOpenChange={(open) => { if (!open && !apply.isPending && !generate.isPending) onClose() }}><DialogContent className="g2-workflow-dialog" onCloseAutoFocus={(event) => { event.preventDefault(); restoreFocus() }} onInteractOutside={(event) => event.preventDefault()}><DialogHeader><DialogTitle>{t(mode === 'template' ? 'g2.templates' : 'g2.ai')}</DialogTitle><DialogDescription>{t(mode === 'template' ? 'g2.templateNotice' : 'g2.aiNotice')}</DialogDescription></DialogHeader>
    {error && <Alert variant="destructive"><AlertDescription>{error.message}<Button size="sm" variant="outline" onClick={() => query.refetch()}><RefreshCw />{t('action.retry')}</Button></AlertDescription></Alert>}
    {stale && <Alert><AlertDescription>{t(mode === 'template' ? 'g2.templateStale' : 'g2.stale')}</AlertDescription></Alert>}
    {query.isLoading ? <p role="status">{t('state.loading')}</p> : <>
      {mode === 'template' ? <label className="g2-select-label">{t('g2.selectTemplate')}<select value={template?.id ?? ''} onChange={(event) => setTemplateId(event.target.value)}>{templates.data?.map((item) => <option key={item.id} value={item.id}>{t(`g2.templateNames.${item.id}`, { defaultValue: item.name })} · v{item.version}</option>)}</select></label> : <div className="g2-workflow-actions">
        {suggestions.data?.length ? <label className="g2-select-label">{t('g2.selectSuggestion')}<select value={suggestion?.id ?? ''} onChange={(event) => { setSuggestionId(event.target.value); setSelected([]); apply.reset() }}>{suggestions.data.map((item) => <option key={item.id} value={item.id}>{new Date(item.createdAt).toLocaleString(i18n.resolvedLanguage)} · {t(item.appliedAt ? 'g2.applied' : `g2.${item.status}`)}</option>)}</select></label> : <p>{t('g2.emptySuggestions')}</p>}
        <Button size="sm" variant="outline" disabled={generate.isPending || active || suggestions.isError || suggestions.isLoading || apply.isPending} onClick={() => generate.mutate()}>{generate.isPending || active ? <LoaderCircle className="animate-spin" /> : <Sparkles />}{t(suggestion ? 'g2.regenerate' : 'g2.generate')}</Button>
        <Button size="icon-sm" variant="ghost" title={t('g2.refresh')} aria-label={t('g2.refresh')} onClick={() => suggestions.refetch()}><RefreshCw /></Button>
      </div>}
      {mode === 'ai' && suggestion && <p role="status">{t(suggestion.appliedAt ? 'g2.applied' : `g2.${suggestion.status}`)}{suggestion.error && ` · ${t(`g2.errors.${suggestion.error.code}`, { defaultValue: suggestion.error.message })}`}</p>}
      {fields.length > 0 && <div className="g2-diff-scroll"><table className="g2-diff-table"><thead><tr><th>{t('fields.key')}</th><th>{t('g2.before')}</th><th>{t('g2.after')}</th></tr></thead><tbody>{fields.map((field) => {
        const before = requirement.fieldDraft?.fields.find((item) => item.key === field.key)
        return <tr key={field.key}><td><label className="g2-field-select">{mode === 'ai' && <Checkbox aria-label={t('g2.reviewChange', { key: field.key })} checked={selected.includes(field.key)} disabled={stale || Boolean(suggestion?.appliedAt) || apply.isPending} onCheckedChange={(checked) => setSelected((keys) => checked ? [...keys, field.key] : keys.filter((key) => key !== field.key))} />}<code>{field.key}</code></label><small>{t(!before ? 'g2.added' : JSON.stringify(before) === JSON.stringify(field) ? 'g2.unchanged' : 'g2.changed')}</small></td><td><FieldContractValue field={before} /></td><td><FieldContractValue field={field} /></td></tr>
      })}</tbody></table></div>}
      {mode === 'template' && (requirement.fieldDraft?.fields ?? []).some((field) => !fields.some((item) => item.key === field.key)) && <p>{t('g2.removed')}: {(requirement.fieldDraft?.fields ?? []).filter((field) => !fields.some((item) => item.key === field.key)).map((field) => field.key).join(', ')}</p>}
      {mode === 'ai' && Boolean(suggestion?.modelInvocations.length) && <details className="requirement-contract-evidence"><summary>{t('g2.modelEvidence')}</summary><pre>{JSON.stringify(suggestion?.modelInvocations, null, 2)}</pre></details>}
    </>}
    <div className="g2-workflow-actions justify-end">{mode === 'ai' && <span>{t('g2.selected', { count: selected.length })}</span>}<Button variant="outline" disabled={apply.isPending || generate.isPending} onClick={onClose}>{t('action.cancel')}</Button><Button disabled={applyDisabled} onClick={() => apply.mutate()}><Check />{t(mode === 'template' ? 'g2.applyTemplate' : 'g2.applySuggestion')}</Button></div>
  </DialogContent></Dialog>
}
