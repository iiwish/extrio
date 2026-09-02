import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import i18next from 'i18next'
import { ArrowLeft, ArrowRight, CheckCircle2, CircleAlert, FileUp, Globe2, Layers3, ListPlus, XCircle } from 'lucide-react'
import { useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { BatchCollectorImportResult } from '@/api/types'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

export interface SourceLineInspection {
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
    returnPath: collectionId ? `/collectors?collection=${encodeURIComponent(collectionId)}` : '/collectors',
  }
}

export function inspectSourceUrls(value: string): SourceLineInspection[] {
  const seen = new Set<string>()
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((raw) => {
    let url: URL
    try {
      url = new URL(raw)
    } catch {
      return { raw, status: 'invalid', message: i18next.t('collectors:create.validation.invalidFormat') }
    }
    if (!['http:', 'https:'].includes(url.protocol)) return { raw, status: 'invalid', message: i18next.t('collectors:create.validation.unsupportedProtocol') }
    const normalized = url.toString()
    if (seen.has(normalized)) return { raw, normalized, host: url.host, status: 'duplicate', message: i18next.t('collectors:create.validation.duplicate') }
    seen.add(normalized)
    return {
      raw,
      normalized,
      host: url.host,
      status: 'valid',
      message: url.protocol === 'http:' ? i18next.t('collectors:create.validation.validHttpRisk') : i18next.t('collectors:create.validation.valid'),
    }
  })
}

export function parseImportedSourceUrls(fileText: string): string[] {
  const seen = new Set<string>()
  const parsed: string[] = []
  for (const part of fileText.split(/[\r\n;,]+/)) {
    const line = part.trim()
    if (!line || seen.has(line)) continue
    seen.add(line)
    parsed.push(line)
  }
  return parsed
}

export function mergeSourceLines(existing: string, imported: string[]): { text: string; added: number; skipped: number } {
  const existingLines = existing.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const seen = new Set(existingLines)
  const added: string[] = []
  let skipped = 0
  for (const line of imported) {
    if (seen.has(line)) {
      skipped += 1
      continue
    }
    seen.add(line)
    added.push(line)
  }
  return { text: [...existingLines, ...added].join('\n'), added: added.length, skipped }
}

export function NewCollectorPage() {
  const { t } = useTranslation('collectors')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const creationContext = collectorCreationContext(searchParams)
  const requestedCollectionId = creationContext.collectionId
  const collectorsQuery = useQuery({ queryKey: ['collectors'], queryFn: api.collectors })
  const [collectionMode, setCollectionMode] = useState<'existing' | 'new'>(creationContext.mode)
  const [selectedCollectionId, setSelectedCollectionId] = useState(requestedCollectionId)
  const [collectionName, setCollectionName] = useState('')
  const [sourceInput, setSourceInput] = useState('')
  const [intent, setIntent] = useState('')
  const [error, setError] = useState('')
  const [importResult, setImportResult] = useState<BatchCollectorImportResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [sourceImportFeedback, setSourceImportFeedback] = useState('')
  const sources = useMemo(() => inspectSourceUrls(sourceInput), [sourceInput])
  const collections = useMemo(() => {
    const byId = new Map<string, { id: string; name: string; intent: string; version: string; collectorCount: number }>()
    for (const collector of collectorsQuery.data ?? []) {
      const current = byId.get(collector.collectionId)
      if (current) current.collectorCount += 1
      else byId.set(collector.collectionId, {
        id: collector.collectionId,
        name: collector.collectionName,
        intent: collector.intent,
        version: collector.collectionVersion,
        collectorCount: 1,
      })
    }
    return [...byId.values()]
  }, [collectorsQuery.data])
  const selectedCollection = collections.find((collection) => collection.id === selectedCollectionId)
    ?? (selectedCollectionId ? undefined : collections[0])
  const activeCollectionMode = !collectorsQuery.isLoading && collections.length === 0 ? 'new' : collectionMode
  const useExistingCollection = activeCollectionMode === 'existing' && Boolean(selectedCollection)
  const validCount = sources.filter((source) => source.status === 'valid').length
  const issueCount = sources.length - validCount
  const mutation = useMutation({
    mutationFn: api.createCollectors,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
      if (result.total === 1 && result.createdCount === 1 && result.results[0].collector) {
        navigate(`/collectors/${result.results[0].collector.id}`)
        return
      }
      setImportResult(result)
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (activeCollectionMode === 'existing' && !selectedCollection) return setError(t('create.error.selectRequirement'))
    if (!useExistingCollection && (!collectionName.trim() || !intent.trim())) return setError(t('create.error.completeNameAndIntent'))
    if (sources.length === 0) return setError(t('create.error.enterUrl'))
    if (validCount === 0) return setError(t('create.error.noImportableUrls'))
    mutation.mutate({
      ...(useExistingCollection ? { collectionId: selectedCollection!.id } : {}),
      collectionName: useExistingCollection ? selectedCollection!.name : collectionName.trim(),
      intent: useExistingCollection ? selectedCollection!.intent : intent.trim(),
      sourceUrls: sources.map((source) => source.raw),
    })
  }

  async function importSourceFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    setSourceImportFeedback('')
    try {
      const parsed = parseImportedSourceUrls(await file.text())
      if (parsed.length === 0) {
        setSourceImportFeedback(t('create.sources.fileEmpty'))
        return
      }
      const merged = mergeSourceLines(sourceInput, parsed)
      setSourceInput(merged.text)
      setSourceImportFeedback(t('create.sources.fileResult', { total: parsed.length, added: merged.added, skipped: merged.skipped }))
    } catch {
      setSourceImportFeedback(t('create.sources.fileReadFailed'))
    }
  }

  if (importResult) {
    return <ImportResult result={importResult} onContinue={() => { setImportResult(null); setSourceInput(''); mutation.reset() }} />
  }

  return (
    <div className="page-frame narrow-page">
      <Link className="back-link" to={creationContext.returnPath}><ArrowLeft />{t('action.backToCollectors')}</Link>
      <header className="page-header form-header">
        <div><h1>{t('create.title')}</h1><p>{t('create.subtitle')}</p></div>
      </header>

      <form className="collector-form collector-create-form" onSubmit={submit} noValidate>
        <section className="collector-create-section">
          <div className="collector-create-heading"><h2>{t('create.requirement.heading')}</h2></div>
          <Tabs value={activeCollectionMode} onValueChange={(value) => setCollectionMode(value as 'existing' | 'new')} className="collection-mode-tabs">
            <TabsList aria-label={t('create.requirement.sourceAria')}><TabsTrigger value="existing" disabled={!collectorsQuery.isLoading && collections.length === 0}>{t('create.requirement.existing')}</TabsTrigger><TabsTrigger value="new">{t('create.requirement.new')}</TabsTrigger></TabsList>
            <TabsContent value="existing" className="collection-mode-panel">
              <label className="field-group"><span>{t('create.requirement.select')}</span><Select value={selectedCollection?.id ?? ''} onValueChange={setSelectedCollectionId}><SelectTrigger aria-label={t('create.requirement.selectExistingAria')}><SelectValue placeholder={collectorsQuery.isLoading ? t('common:state.loading') : t('create.requirement.select')} /></SelectTrigger><SelectContent>{collections.map((collection) => <SelectItem key={collection.id} value={collection.id}>{collection.name}</SelectItem>)}</SelectContent></Select></label>
              {selectedCollection && <div className="existing-collection-summary"><span><small>{t('create.requirement.intentLabel')}</small><p>{selectedCollection.intent}</p></span><span><small>{t('create.requirement.contractLabel')}</small><code>{selectedCollection.version}</code></span><span><small>{t('create.requirement.collectorLabel')}</small><strong>{selectedCollection.collectorCount}</strong></span></div>}
            </TabsContent>
            <TabsContent value="new" className="collection-mode-panel new-collection-fields">
              <label className="field-group" htmlFor="collection-name"><span>{t('create.requirement.nameLabel')}</span><Input id="collection-name" value={collectionName} onChange={(event) => setCollectionName(event.target.value)} placeholder={t('create.requirement.namePlaceholder')} /></label>
              <label className="field-group" htmlFor="intent"><span>{t('create.requirement.intentLabel')}</span><Textarea id="intent" value={intent} onChange={(event) => setIntent(event.target.value)} placeholder={t('create.requirement.intentPlaceholder')} rows={4} /></label>
            </TabsContent>
          </Tabs>
        </section>

        <section className="collector-create-section source-entry-section">
          <div className="collector-create-heading"><h2>{t('create.sources.heading')}</h2>{sources.length > 0 && <span>{t('create.sources.countSummary', { valid: validCount, issues: issueCount })}</span>}<Button type="button" variant="outline" size="sm" aria-label={t('create.sources.importAria')} onClick={() => fileInputRef.current?.click()}><FileUp />{t('create.sources.import')}</Button><input ref={fileInputRef} className="sr-only" type="file" accept=".txt,.csv,text/plain,text/csv" aria-label={t('create.sources.importAria')} onChange={(event) => void importSourceFile(event)} />{sourceImportFeedback && <span className="source-import-feedback" role="status">{sourceImportFeedback}</span>}</div>
          <div className="form-fields">
            <div className="field-group">
              <div className="source-batch-input"><Globe2 /><Textarea id="source-urls" value={sourceInput} onChange={(event) => setSourceInput(event.target.value)} placeholder={'http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm\nhttps://ggzy.beijing.gov.cn/notices\nhttps://example.gov.cn/tender/list'} rows={7} /></div>
            </div>

            {sources.length > 0 && <div className="source-import-preview" aria-label={t('create.sources.previewAria')}>
              {sources.slice(0, 8).map((source, index) => <div className={source.status} key={`${source.raw}-${index}`}>
                <span>{source.status === 'valid' ? <CheckCircle2 /> : source.status === 'duplicate' ? <CircleAlert /> : <XCircle />}</span>
                <code>{source.raw}</code>
                <small>{source.message}</small>
              </div>)}
              {sources.length > 8 && <p>{t('create.sources.moreCount', { count: sources.length - 8 })}</p>}
            </div>}
          </div>
        </section>

        {(error || mutation.error) && <Alert variant="destructive"><AlertDescription>{error || mutation.error?.message}</AlertDescription></Alert>}

        <div className="form-actions">
          <Button asChild variant="ghost"><Link to={creationContext.returnPath}>{t('common:action.cancel')}</Link></Button>
          <Button type="submit" size="lg" disabled={mutation.isPending}>
            {mutation.isPending ? t('create.creating') : <><ListPlus />{t('create.createCount', { count: validCount || 0 })}<ArrowRight /></>}
          </Button>
        </div>
      </form>
    </div>
  )
}

function ImportResult({ result, onContinue }: { result: BatchCollectorImportResult; onContinue: () => void }) {
  const { t } = useTranslation('collectors')
  return <div className="page-frame narrow-page">
    <Link className="back-link" to="/collectors"><ArrowLeft />{t('action.backToCollectors')}</Link>
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
    <div className="form-actions"><Button asChild><Link to={`/collectors?collection=${encodeURIComponent(result.collectionId)}`}>{t('result.viewCollectors')}<ArrowRight /></Link></Button></div>
  </div>
}
