import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, CheckCircle2, CircleAlert, FileUp, Globe2, Layers3, ListPlus, XCircle } from 'lucide-react'
import { useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
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
      return { raw, status: 'invalid', message: 'URL 格式无效' }
    }
    if (!['http:', 'https:'].includes(url.protocol)) return { raw, status: 'invalid', message: '仅支持 HTTP 或 HTTPS' }
    const normalized = url.toString()
    if (seen.has(normalized)) return { raw, normalized, host: url.host, status: 'duplicate', message: '批次内重复' }
    seen.add(normalized)
    return {
      raw,
      normalized,
      host: url.host,
      status: 'valid',
      message: url.protocol === 'http:' ? '可导入 · 匿名 HTTP 风险已标记' : '可导入',
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
    if (activeCollectionMode === 'existing' && !selectedCollection) return setError('请选择一个已有需求。')
    if (!useExistingCollection && (!collectionName.trim() || !intent.trim())) return setError('请补全需求名称与采集意图。')
    if (sources.length === 0) return setError('请至少输入一个采集入口 URL。')
    if (validCount === 0) return setError('当前批次没有可导入的 HTTP(S) URL。')
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
        setSourceImportFeedback('文件中未找到有效网址')
        return
      }
      const merged = mergeSourceLines(sourceInput, parsed)
      setSourceInput(merged.text)
      setSourceImportFeedback(`已导入 ${parsed.length} 条，新增 ${merged.added} 条，跳过 ${merged.skipped} 条重复`)
    } catch {
      setSourceImportFeedback('文件读取失败，请重试')
    }
  }

  if (importResult) {
    return <ImportResult result={importResult} onContinue={() => { setImportResult(null); setSourceInput(''); mutation.reset() }} />
  }

  return (
    <div className="page-frame narrow-page">
      <Link className="back-link" to={creationContext.returnPath}><ArrowLeft />返回采集器</Link>
      <header className="page-header form-header">
        <div><h1>新建采集器</h1><p>选择需求并添加一个或多个入口网址。</p></div>
      </header>

      <form className="collector-form collector-create-form" onSubmit={submit} noValidate>
        <section className="collector-create-section">
          <div className="collector-create-heading"><h2>归属需求</h2></div>
          <Tabs value={activeCollectionMode} onValueChange={(value) => setCollectionMode(value as 'existing' | 'new')} className="collection-mode-tabs">
            <TabsList aria-label="需求来源"><TabsTrigger value="existing" disabled={!collectorsQuery.isLoading && collections.length === 0}>已有需求</TabsTrigger><TabsTrigger value="new">新建需求</TabsTrigger></TabsList>
            <TabsContent value="existing" className="collection-mode-panel">
              <label className="field-group"><span>选择需求</span><Select value={selectedCollection?.id ?? ''} onValueChange={setSelectedCollectionId}><SelectTrigger aria-label="选择已有需求"><SelectValue placeholder={collectorsQuery.isLoading ? '加载中…' : '选择需求'} /></SelectTrigger><SelectContent>{collections.map((collection) => <SelectItem key={collection.id} value={collection.id}>{collection.name}</SelectItem>)}</SelectContent></Select></label>
              {selectedCollection && <div className="existing-collection-summary"><span><small>采集意图</small><p>{selectedCollection.intent}</p></span><span><small>数据合同</small><code>{selectedCollection.version}</code></span><span><small>采集器</small><strong>{selectedCollection.collectorCount}</strong></span></div>}
            </TabsContent>
            <TabsContent value="new" className="collection-mode-panel new-collection-fields">
              <label className="field-group" htmlFor="collection-name"><span>需求名称</span><Input id="collection-name" value={collectionName} onChange={(event) => setCollectionName(event.target.value)} placeholder="例如：全国公共资源交易标讯" /></label>
              <label className="field-group" htmlFor="intent"><span>采集意图</span><Textarea id="intent" value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="描述需要采集的内容与关键字段" rows={4} /></label>
            </TabsContent>
          </Tabs>
        </section>

        <section className="collector-create-section source-entry-section">
          <div className="collector-create-heading"><h2>入口网址</h2>{sources.length > 0 && <span>{validCount} 可创建 · {issueCount} 有问题</span>}<Button type="button" variant="outline" size="sm" aria-label="从文件导入网址" onClick={() => fileInputRef.current?.click()}><FileUp />导入</Button><input ref={fileInputRef} className="sr-only" type="file" accept=".txt,.csv,text/plain,text/csv" aria-label="从文件导入网址" onChange={(event) => void importSourceFile(event)} />{sourceImportFeedback && <span className="source-import-feedback" role="status">{sourceImportFeedback}</span>}</div>
          <div className="form-fields">
            <div className="field-group">
              <div className="source-batch-input"><Globe2 /><Textarea id="source-urls" value={sourceInput} onChange={(event) => setSourceInput(event.target.value)} placeholder={'http://www.ccgp-beijing.gov.cn/yxgk/sjcgyx/A002003001index_1.htm\nhttps://ggzy.beijing.gov.cn/notices\nhttps://example.gov.cn/tender/list'} rows={7} /></div>
            </div>

            {sources.length > 0 && <div className="source-import-preview" aria-label="Source 导入预览">
              {sources.slice(0, 8).map((source, index) => <div className={source.status} key={`${source.raw}-${index}`}>
                <span>{source.status === 'valid' ? <CheckCircle2 /> : source.status === 'duplicate' ? <CircleAlert /> : <XCircle />}</span>
                <code>{source.raw}</code>
                <small>{source.message}</small>
              </div>)}
              {sources.length > 8 && <p>另有 {sources.length - 8} 条 URL，将在提交后逐项处理。</p>}
            </div>}
          </div>
        </section>

        {(error || mutation.error) && <Alert variant="destructive"><AlertDescription>{error || mutation.error?.message}</AlertDescription></Alert>}

        <div className="form-actions">
          <Button asChild variant="ghost"><Link to={creationContext.returnPath}>取消</Link></Button>
          <Button type="submit" size="lg" disabled={mutation.isPending}>
            {mutation.isPending ? '正在创建…' : <><ListPlus />创建 {validCount || 0} 个采集器<ArrowRight /></>}
          </Button>
        </div>
      </form>
    </div>
  )
}

function ImportResult({ result, onContinue }: { result: BatchCollectorImportResult; onContinue: () => void }) {
  return <div className="page-frame narrow-page">
    <Link className="back-link" to="/collectors"><ArrowLeft />返回采集器</Link>
    <header className="page-header"><div><span className="eyebrow">BATCH IMPORT RESULT</span><h1>Source 导入完成</h1><p>{result.collectionName} · {result.collectionVersion}</p></div><Button variant="outline" onClick={onContinue}><ListPlus />继续导入</Button></header>
    <section className="import-collection-context" aria-label="采集需求归属"><span className="collection-mark"><Layers3 /></span><div><small>采集需求</small><strong>{result.collectionName}</strong><code>{result.collectionVersion}</code></div><span><small>独立采集器</small><strong>{result.createdCount}</strong></span></section>
    <div className="import-result-summary"><span><small>总数</small><strong>{result.total}</strong></span><span className="success"><small>已创建</small><strong>{result.createdCount}</strong></span><span className={result.rejectedCount > 0 ? 'danger' : ''}><small>已拒绝</small><strong>{result.rejectedCount}</strong></span></div>
    <section className="import-result-card" aria-label="逐项导入结果">
      {result.results.map((item, index) => <div className="import-result-row" key={`${item.sourceUrl}-${index}`}>
        <span className={item.status === 'created' ? 'import-status success' : 'import-status danger'}>{item.status === 'created' ? <CheckCircle2 /> : <XCircle />}</span>
        <span><strong>{item.collector?.name ?? item.sourceUrl}</strong><small>{item.collector?.sourceHost ?? item.error?.message ?? '导入失败'}</small></span>
        <span className={item.status === 'created' ? 'result-label success' : 'result-label danger'}>{item.status === 'created' ? '已创建' : item.error?.message ?? '导入失败'}</span>
        {item.collector ? <Button asChild size="sm" variant="outline"><Link to={`/collectors/${item.collector.id}`}>开始探索<ArrowRight /></Link></Button> : <span />}
      </div>)}
    </section>
    <div className="form-actions"><Button asChild><Link to={`/collectors?collection=${encodeURIComponent(result.collectionId)}`}>查看此需求的 Collector<ArrowRight /></Link></Button></div>
  </div>
}
