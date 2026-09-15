import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import i18next from 'i18next'
import { ArrowRight, CheckCircle2, CircleAlert, CircleHelp, Download, FileUp, Globe2, Layers3, ListPlus, Trash2, XCircle } from 'lucide-react'
import { useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useBeforeUnload, useBlocker, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { BatchCollectorImportResult, CreateCollectorsInput } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { returnTarget } from '@/lib/workspace-navigation'
import { CollectorsPage } from './collectors-page'
import './new-collector.css'
import {
  MAX_SOURCE_FILE_BYTES,
  MAX_SOURCE_ROWS,
  SourceFileError,
  manualSourceDrafts,
  parseSourceFile,
  type SourceDraft,
} from './source-file-import'

export interface SourceLineInspection extends SourceDraft {
  raw: string
  normalized?: string
  host?: string
  status: 'valid' | 'invalid' | 'duplicate'
  message: string
}

export function collectorCreationContext(searchParams: URLSearchParams) {
  const collectionId = searchParams.get('collection')?.trim() ?? ''
  return {
    collectionId,
    mode: collectionId ? 'existing' as const : 'new' as const,
    returnPath: returnTarget(searchParams, collectionId ? `/collections/${encodeURIComponent(collectionId)}` : '/collectors'),
  }
}

export function inspectSourceDrafts(drafts: SourceDraft[]): SourceLineInspection[] {
  const seen = new Set<string>()
  return drafts.map((draft, index) => {
    const raw = draft.entryUrl
    const base = { ...draft, raw }
    if (index >= MAX_SOURCE_ROWS) return { ...base, status: 'invalid', message: i18next.t('collectors:create.validation.rowLimit') }
    if (draft.mode !== 'exact') return { ...base, status: 'invalid', message: i18next.t('collectors:create.validation.unsupportedMode') }
    if (draft.name.length > 200) return { ...base, status: 'invalid', message: i18next.t('collectors:create.validation.nameTooLong') }
    if (draft.scopeHint.length > 1000) return { ...base, status: 'invalid', message: i18next.t('collectors:create.validation.scopeTooLong') }
    let url: URL
    try {
      url = new URL(raw)
    } catch {
      return { ...base, status: 'invalid', message: i18next.t('collectors:create.validation.invalidFormat') }
    }
    if (!['http:', 'https:'].includes(url.protocol)) {
      return { ...base, status: 'invalid', message: i18next.t('collectors:create.validation.unsupportedProtocol') }
    }
    const normalized = url.toString()
    if ((url.pathname === '' || url.pathname === '/') && !url.search) {
      return { ...base, normalized, host: url.host, status: 'invalid', message: i18next.t('collectors:create.validation.exactEntryRequired') }
    }
    if (seen.has(normalized)) {
      return { ...base, normalized, host: url.host, status: 'duplicate', message: i18next.t('collectors:create.validation.duplicate') }
    }
    seen.add(normalized)
    return {
      ...base,
      normalized,
      host: url.host,
      status: 'valid',
      message: url.protocol === 'http:' ? i18next.t('collectors:create.validation.validHttpRisk') : i18next.t('collectors:create.validation.valid'),
    }
  })
}

export function inspectSourceUrls(value: string): SourceLineInspection[] {
  return inspectSourceDrafts(manualSourceDrafts(value))
}

function downloadCsvTemplate() {
  const content = [
    'entryUrl,mode,name,scopeHint',
    'http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm,exact,北京市级采购意向,采集北京市级预算单位采购意向',
    'http://www.ccgp-beijing.gov.cn/yxgk/qjcgyx/A002003002index_1.htm,,北京区级采购意向,采集北京市区级预算单位采购意向',
  ].join('\r\n')
  const url = URL.createObjectURL(new Blob([`\uFEFF${content}`], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'extrio-collector-import.csv'
  anchor.click()
  URL.revokeObjectURL(url)
}

export function NewCollectorPage() {
  const { t } = useTranslation('collectors')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const creationContext = collectorCreationContext(searchParams)
  const requestedCollectionId = creationContext.collectionId
  const collectorsQuery = useQuery({ queryKey: ['collections'], queryFn: api.collections })
  const [collectionMode, setCollectionMode] = useState<'existing' | 'new'>(creationContext.mode)
  const [selectedCollectionId, setSelectedCollectionId] = useState(requestedCollectionId)
  const [collectionName, setCollectionName] = useState('')
  const [sourceInput, setSourceInput] = useState('')
  const [importedSources, setImportedSources] = useState<SourceDraft[]>([])
  const [sourceFilter, setSourceFilter] = useState<'all' | 'valid' | 'issues'>('all')
  const [intent, setIntent] = useState('')
  const [formErrors, setFormErrors] = useState<{ collection?: string; intent?: string; sources?: string }>({})
  const [importResult, setImportResult] = useState<BatchCollectorImportResult | null>(null)
  const submittedRef = useRef(false)
  const dirty = Boolean(sourceInput.trim() || importedSources.length || collectionName.trim() || intent.trim())
  const blocker = useBlocker(({currentLocation,nextLocation}) => !submittedRef.current && dirty && `${currentLocation.pathname}${currentLocation.search}` !== `${nextLocation.pathname}${nextLocation.search}`)
  useBeforeUnload(event => { if (dirty && !submittedRef.current) { event.preventDefault(); event.returnValue = '' } })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const collectionNameRef = useRef<HTMLInputElement>(null)
  const intentRef = useRef<HTMLTextAreaElement>(null)
  const sourceInputRef = useRef<HTMLTextAreaElement>(null)
  const [importedFileName, setImportedFileName] = useState('')
  const [sourceImportError, setSourceImportError] = useState('')
  const sourceDrafts = useMemo(() => [...importedSources, ...manualSourceDrafts(sourceInput)], [sourceInput, importedSources])
  const sources = useMemo(() => inspectSourceDrafts(sourceDrafts), [sourceDrafts])
  const collections = useMemo(() => {
    return (collectorsQuery.data ?? []).filter((value) => value.status === 'active').map((value) => ({
      id: value.id, name: value.name, intent: value.intent, version: value.activeVersionId ?? value.collectionVersion, collectorCount: value.sourceCount,
    }))
  }, [collectorsQuery.data])
  const selectedCollection = collections.find((collection) => collection.id === selectedCollectionId)
    ?? (selectedCollectionId ? undefined : collections[0])
  const activeCollectionMode = !requestedCollectionId && collectorsQuery.isSuccess && collections.length === 0 ? 'new' : collectionMode
  const useExistingCollection = activeCollectionMode === 'existing' && Boolean(selectedCollection)
  const validSources = sources.filter((source) => source.status === 'valid')
  const validCount = validSources.length
  const issueCount = sources.length - validCount
  const visibleSources = sources.filter((source) => sourceFilter === 'all'
    || (sourceFilter === 'valid' ? source.status === 'valid' : source.status !== 'valid'))
  const requirementReady = useExistingCollection || Boolean(collectionName.trim() && intent.trim())

  const mutation = useMutation({
    mutationFn: (input: CreateCollectorsInput) => api.createCollectors(input),
    onSuccess: (result) => {
      submittedRef.current = true
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
      queryClient.invalidateQueries({ queryKey: ['collections'] })
      queryClient.invalidateQueries({ queryKey: ['collection'] })
      if (result.total === 1 && result.createdCount === 1 && result.results[0].collector) {
        navigate(`/collectors/${result.results[0].collector.id}`)
        return
      }
      setImportResult(result)
    },
  })
  const canSubmit = requirementReady && validCount > 0 && !mutation.isPending && !collectorsQuery.isError
    && (activeCollectionMode !== 'existing' || Boolean(selectedCollection))

  function submit(event: FormEvent) {
    event.preventDefault()
    if (mutation.isPending) return
    const nextErrors: typeof formErrors = {}
    if (activeCollectionMode === 'existing' && !selectedCollection) nextErrors.collection = t('create.error.selectRequirement')
    if (!useExistingCollection && !collectionName.trim()) nextErrors.collection = t('create.error.requirementName')
    if (!useExistingCollection && !intent.trim()) nextErrors.intent = t('create.error.intent')
    if (sources.length === 0) nextErrors.sources = t('create.error.enterUrl')
    else if (validCount === 0) nextErrors.sources = t('create.error.noImportableUrls')
    setFormErrors(nextErrors)
    if (collectorsQuery.isError) return
    if (Object.keys(nextErrors).length > 0) {
      requestAnimationFrame(() => {
        if (nextErrors.collection && !useExistingCollection) collectionNameRef.current?.focus()
        else if (nextErrors.intent) intentRef.current?.focus()
        else if (nextErrors.sources) sourceInputRef.current?.focus()
      })
      return
    }
    mutation.mutate({
      ...(useExistingCollection ? { collectionId: selectedCollection!.id } : {}),
      collectionName: useExistingCollection ? selectedCollection!.name : collectionName.trim(),
      intent: useExistingCollection ? selectedCollection!.intent : intent.trim(),
      sources: validSources.map((source) => ({
        entryUrl: source.normalized ?? source.entryUrl,
        mode: 'exact',
        ...(source.name ? { name: source.name } : {}),
        ...(source.scopeHint ? { scopeHint: source.scopeHint } : {}),
      })),
    })
  }

  async function importSourceFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    setSourceImportError('')
    if (file.size > MAX_SOURCE_FILE_BYTES) {
      setSourceImportError(t('create.sources.fileError', { fileName: file.name, message: t('create.sources.errors.fileTooLarge') }))
      return
    }
    try {
      const batchId = `${Date.now()}-${file.name}`
      const parsed = parseSourceFile(file.name, await file.text()).map((source) => ({ ...source, id: `${batchId}-${source.id}` }))
      setImportedSources(parsed)
      setImportedFileName(file.name)
      setSourceFilter('all')
      setFormErrors((current) => ({ ...current, sources: undefined }))
    } catch (error) {
      const code = error instanceof SourceFileError ? error.code : 'parseFailed'
      setSourceImportError(t('create.sources.fileError', { fileName: file.name, message: t(`create.sources.errors.${code}`) }))
    }
  }

  function removeSource(source: SourceLineInspection) {
    if (source.origin === 'file') {
      const nextSources = importedSources.filter((item) => item.id !== source.id)
      setImportedSources(nextSources)
      if (nextSources.length === 0) setImportedFileName('')
      return
    }
    const lines = sourceInput.split(/\r?\n/)
    lines.splice(source.lineNumber - 1, 1)
    setSourceInput(lines.join('\n'))
  }

  function clearImportedSources() {
    setImportedSources([])
    setImportedFileName('')
    setSourceImportError('')
    setSourceFilter('all')
  }

  const readiness = !requirementReady
    ? t('create.readiness.requirement')
    : validCount === 0
      ? t('create.readiness.sources')
      : issueCount > 0
        ? t('create.readiness.partial', { count: validCount, issues: issueCount })
        : t('create.readiness.ready', { count: validCount })

  if (importResult) {
    return <ImportResult result={importResult} onContinue={() => {
      submittedRef.current = false
      setImportResult(null)
      setSourceInput('')
      setImportedSources([])
      setImportedFileName('')
      setSourceImportError('')
      mutation.reset()
    }} />
  }

  return (
    <>
      <CollectorsPage />
      <Dialog open onOpenChange={(open) => { if (!open && !mutation.isPending) navigate(creationContext.returnPath) }}>
      <DialogContent className="collector-create-dialog" aria-describedby={undefined} showCloseButton={!mutation.isPending} onInteractOutside={(event) => event.preventDefault()} onEscapeKeyDown={(event) => { if (mutation.isPending || blocker.state === 'blocked') event.preventDefault() }}>
      <DialogHeader><DialogTitle>{t('create.title')}</DialogTitle></DialogHeader>
      <form className="collector-form collector-create-form" onSubmit={submit} noValidate>
        {collectorsQuery.isError && <Alert variant="destructive"><AlertDescription>{collectorsQuery.error.message}<Button type="button" variant="outline" onClick={() => collectorsQuery.refetch()}>{t('common:action.retry')}</Button></AlertDescription></Alert>}
        {requestedCollectionId && collectorsQuery.isSuccess && !collections.some((value) => value.id === requestedCollectionId)
          && <Alert><AlertDescription>{t('common:collections.unavailable')}</AlertDescription></Alert>}
        <section className="collector-create-section">
          <div className="collector-create-heading"><h2>{t('create.requirement.heading')}</h2></div>
          <Tabs value={activeCollectionMode} onValueChange={(value) => { setCollectionMode(value as 'existing' | 'new'); setFormErrors({}) }} className="collection-mode-tabs">
            <TabsList aria-label={t('create.requirement.sourceAria')}><TabsTrigger value="existing" disabled={!collectorsQuery.isLoading && collections.length === 0}>{t('create.requirement.existing')}</TabsTrigger><TabsTrigger value="new">{t('create.requirement.new')}</TabsTrigger></TabsList>
            <TabsContent value="existing" className="collection-mode-panel">
              <label className="field-group"><span>{t('create.requirement.select')}</span><Select disabled={collectorsQuery.isLoading} value={selectedCollectionId || selectedCollection?.id || ''} onValueChange={(value) => { if (!value) return; setSelectedCollectionId(value); setFormErrors((current) => ({ ...current, collection: undefined })) }}><SelectTrigger aria-label={t('create.requirement.selectExistingAria')} aria-invalid={Boolean(formErrors.collection)}><SelectValue placeholder={collectorsQuery.isLoading ? t('common:state.loading') : t('create.requirement.select')} /></SelectTrigger><SelectContent>{collections.map((collection) => <SelectItem key={collection.id} value={collection.id}>{collection.name}</SelectItem>)}</SelectContent></Select>{formErrors.collection && <small className="field-error">{formErrors.collection}</small>}</label>
              {selectedCollection && <div className="existing-collection-summary"><span><small>{t('create.requirement.intentLabel')}</small><p>{selectedCollection.intent}</p></span><span><small>{t('create.requirement.contractLabel')}</small><code>{selectedCollection.version}</code></span><span><small>{t('create.requirement.collectorLabel')}</small><strong>{selectedCollection.collectorCount}</strong></span></div>}
            </TabsContent>
            <TabsContent value="new" className="collection-mode-panel new-collection-fields">
              <label className="field-group" htmlFor="collection-name"><span>{t('create.requirement.nameLabel')}</span><Input ref={collectionNameRef} id="collection-name" value={collectionName} aria-invalid={Boolean(formErrors.collection)} aria-describedby={formErrors.collection ? 'collection-name-error' : undefined} onChange={(event) => { setCollectionName(event.target.value); setFormErrors((current) => ({ ...current, collection: undefined })) }} placeholder={t('create.requirement.namePlaceholder')} />{formErrors.collection && <small id="collection-name-error" className="field-error">{formErrors.collection}</small>}</label>
              <label className="field-group" htmlFor="intent"><span>{t('create.requirement.intentLabel')}</span><Textarea ref={intentRef} id="intent" value={intent} aria-invalid={Boolean(formErrors.intent)} aria-describedby={formErrors.intent ? 'intent-error' : undefined} onChange={(event) => { setIntent(event.target.value); setFormErrors((current) => ({ ...current, intent: undefined })) }} placeholder={t('create.requirement.intentPlaceholder')} rows={4} />{formErrors.intent && <small id="intent-error" className="field-error">{formErrors.intent}</small>}</label>
            </TabsContent>
          </Tabs>
        </section>

        <section className="collector-create-section source-entry-section">
          <div className="collector-create-heading source-heading">
            <div><h2>{t('create.sources.heading')}</h2><p>{t('create.sources.headingHelp')}</p></div>
            <div className="source-file-actions">
              <TooltipProvider delayDuration={300}><Tooltip>
                <TooltipTrigger asChild><Button type="button" variant="ghost" size="icon-sm" className="source-format-help" aria-label={t('create.sources.formatTitle')}><CircleHelp /></Button></TooltipTrigger>
                <TooltipContent side="bottom" align="end">{t('create.sources.formatHelp')}</TooltipContent>
              </Tooltip></TooltipProvider>
              <Button type="button" variant="ghost" size="sm" onClick={downloadCsvTemplate}><Download />{t('create.sources.template')}</Button>
              <Button type="button" variant="outline" size="sm" aria-label={t('create.sources.importAria')} onClick={() => fileInputRef.current?.click()}><FileUp />{t('create.sources.import')}</Button>
              <input ref={fileInputRef} hidden tabIndex={-1} type="file" accept=".txt,.csv,text/plain,text/csv" onChange={(event) => void importSourceFile(event)} />
            </div>
          </div>
          <span className="sr-only" id="source-format-help">{t('create.sources.formatHelp')}</span>
          {sourceImportError && <Alert className="source-import-error" variant="destructive" role="alert"><AlertDescription>{sourceImportError}</AlertDescription></Alert>}
          <div className="form-fields source-form-fields">
            <label className="field-group" htmlFor="source-urls">
              <span>{t('create.sources.manualLabel')}</span>
              <div className="source-batch-input"><Globe2 /><Textarea ref={sourceInputRef} id="source-urls" value={sourceInput} aria-invalid={Boolean(formErrors.sources)} aria-describedby={`source-format-help${formErrors.sources ? ' source-error' : ''}`} onChange={(event) => { setSourceInput(event.target.value); setFormErrors((current) => ({ ...current, sources: undefined })) }} placeholder={'http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm\nhttp://www.ccgp-beijing.gov.cn/yxgk/qjcgyx/A002003002index_1.htm'} rows={6} /></div>
              {formErrors.sources && <small id="source-error" className="field-error">{formErrors.sources}</small>}
            </label>

            {sources.length > 0 && <div className="source-import-summary" role="status">
              <span>{importedFileName ? t('create.sources.fileResult', { fileName: importedFileName, total: importedSources.length }) : t('create.sources.manualSummary')}</span>
              <div className="source-import-summary-actions">
                <strong>{t('create.sources.countSummary', { total: sources.length, valid: validCount, issues: issueCount })}</strong>
                {importedFileName && <Button type="button" variant="ghost" size="sm" onClick={clearImportedSources}><Trash2 />{t('create.sources.clearFile')}</Button>}
              </div>
            </div>}

            {sources.length > 0 && <div className="source-preview-shell">
              <div className="source-preview-toolbar">
                <div className="segmented" role="group" aria-label={t('create.sources.filterAria')}>
                  {(['all', 'valid', 'issues'] as const).map((filter) => <Button type="button" key={filter} variant={sourceFilter === filter ? 'secondary' : 'ghost'} size="sm" aria-pressed={sourceFilter === filter} onClick={() => setSourceFilter(filter)}>{t(`create.sources.filters.${filter}`, { count: filter === 'all' ? sources.length : filter === 'valid' ? validCount : issueCount })}</Button>)}
                </div>
                <span>{t('create.sources.exactOnly')}</span>
              </div>
              <div className="source-import-preview" role="table" aria-label={t('create.sources.previewAria')}>
                <div className="source-preview-header" role="row"><span role="columnheader">{t('create.sources.columns.row')}</span><span role="columnheader">{t('create.sources.columns.source')}</span><span role="columnheader">{t('create.sources.columns.name')}</span><span role="columnheader">{t('create.sources.columns.mode')}</span><span role="columnheader">{t('create.sources.columns.status')}</span><span role="columnheader" aria-label={t('create.sources.columns.actions')} /></div>
                {visibleSources.map((source) => <div className={`source-preview-row ${source.status}`} role="row" key={source.id}>
                  <span className="source-row-number" role="cell">{source.origin === 'file' ? t('create.sources.fileRow', { row: source.lineNumber }) : source.lineNumber}</span>
                  <code role="cell" title={source.entryUrl}>{source.entryUrl || t('create.sources.missingUrl')}</code>
                  <span className="source-row-name" role="cell"><strong>{source.name || source.host || '—'}</strong>{source.scopeHint && <small title={source.scopeHint}>{source.scopeHint}</small>}</span>
                  <span role="cell"><span className="source-mode">{source.mode || 'exact'}</span></span>
                  <span className="source-status" role="cell">{source.status === 'valid' ? <CheckCircle2 /> : source.status === 'duplicate' ? <CircleAlert /> : <XCircle />}<small>{source.message}</small></span>
                  <span className="source-row-action" role="cell"><Button type="button" variant="ghost" size="icon-sm" title={t('create.sources.remove')} aria-label={t('create.sources.removeRow', { row: source.lineNumber })} onClick={() => removeSource(source)}><Trash2 /></Button></span>
                </div>)}
                {visibleSources.length === 0 && <p>{t('create.sources.filterEmpty')}</p>}
              </div>
            </div>}
          </div>
        </section>

        {mutation.error && <Alert variant="destructive"><AlertDescription>{mutation.error.message}</AlertDescription></Alert>}

        <div className="form-actions collector-create-actions">
          <span className={canSubmit ? 'form-readiness ready' : 'form-readiness'}>{readiness}</span>
          <Button type="button" variant="ghost" disabled={mutation.isPending} onClick={() => navigate(creationContext.returnPath)}>{t('common:action.cancel')}</Button>
          <Button type="submit" size="lg" disabled={!canSubmit}>
            {mutation.isPending ? t('create.creating') : <><ListPlus />{t('create.createCount', { count: validCount })}<ArrowRight /></>}
          </Button>
        </div>
      </form>
      </DialogContent>
      </Dialog>
      <Dialog open={blocker.state === 'blocked'} onOpenChange={open => { if (!open && blocker.state === 'blocked') blocker.reset() }}>
        <DialogContent onCloseAutoFocus={event => { event.preventDefault(); sourceInputRef.current?.focus() }}><DialogHeader><DialogTitle>{t('leave.title')}</DialogTitle><DialogDescription>{t('leave.description')}</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" disabled={mutation.isPending} onClick={() => blocker.state === 'blocked' && blocker.reset()}>{t('common:fields.keepEditing')}</Button><Button variant="destructive" disabled={mutation.isPending} onClick={() => blocker.state === 'blocked' && blocker.proceed()}>{t('common:fields.discardLeave')}</Button></DialogFooter></DialogContent>
      </Dialog>
    </>
  )
}

function ImportResult({ result, onContinue }: { result: BatchCollectorImportResult; onContinue: () => void }) {
  const { t } = useTranslation('collectors')
  return <div className="page-frame narrow-page">
    <header className="page-header"><div><span className="eyebrow">BATCH IMPORT RESULT</span><h1>{t('result.title')}</h1><p>{result.collectionName} · {result.collectionVersion}</p></div><Button variant="outline" onClick={onContinue}><ListPlus />{t('result.continue')}</Button></header>
    <section className="import-collection-context" aria-label={t('result.contextAria')}><span className="collection-mark"><Layers3 /></span><div><small>{t('result.requirementLabel')}</small><strong>{result.collectionName}</strong><code>{result.collectionVersion}</code></div><span><small>{t('result.individualCollectors')}</small><strong>{result.createdCount}</strong></span></section>
    <div className="import-result-summary"><span><small>{t('result.total')}</small><strong>{result.total}</strong></span><span className="success"><small>{t('result.created')}</small><strong>{result.createdCount}</strong></span><span className={result.rejectedCount > 0 ? 'danger' : ''}><small>{t('result.rejected')}</small><strong>{result.rejectedCount}</strong></span></div>
    <section className="import-result-card" aria-label={t('result.perItemAria')}>
      {result.results.map((item, index) => <div className="import-result-row" key={`${item.sourceUrl}-${index}`}>
        <span className={item.status === 'created' ? 'import-status success' : 'import-status danger'}>{item.status === 'created' ? <CheckCircle2 /> : <XCircle />}</span>
        <span><strong>{item.collector?.name ?? item.sourceUrl}</strong><small>{item.collector?.sourceHost ?? item.error?.message ?? t('result.failed')}</small></span>
        <span className={item.status === 'created' ? 'result-label success' : 'result-label danger'}>{item.status === 'created' ? t('result.created') : item.error?.message ?? t('result.failed')}</span>
        {item.collector ? <Button asChild size="sm" variant="outline"><Link to={`/collectors/${item.collector.id}`}>{t('result.startExploring')}<ArrowRight /></Link></Button> : <span />}
      </div>)}
    </section>
    <div className="form-actions"><Button asChild><Link to={`/collections/${encodeURIComponent(result.collectionId)}`}>{t('result.viewCollectors')}<ArrowRight /></Link></Button></div>
  </div>
}
