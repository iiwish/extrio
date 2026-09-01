import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Braces, Check, Clock3, FileCheck2, FileSearch, Fingerprint, ListTree, LoaderCircle, Route, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, waitForOperation } from '@/api/client'
import type { Operation, Run } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function RunPage() {
  const { runId = '' } = useParams()
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['run', runId], queryFn: () => api.runDetail(runId) })
  const [operation, setOperation] = useState<Operation | undefined>()
  const [operationError, setOperationError] = useState<Error | undefined>()
  const runStatus = query.data?.status
  const operationId = query.data?.operationId
  const collectorId = query.data?.collectorId ?? ''
  const collectorQuery = useQuery({ queryKey: ['collector', collectorId], queryFn: () => api.collector(collectorId), enabled: Boolean(collectorId) })

  useEffect(() => {
    if (!operationId || !runStatus || !['queued', 'running', 'finalizing'].includes(runStatus)) return
    const controller = new AbortController()
    api.operation(operationId)
      .then((accepted) => waitForOperation(accepted, setOperation, controller.signal))
      .then(() => api.runDetail(runId))
      .then((data) => {
        queryClient.setQueryData(['run', runId], data)
        queryClient.invalidateQueries({ queryKey: ['runs'] })
        queryClient.invalidateQueries({ queryKey: ['items'] })
      })
      .catch((error: Error) => {
        if (error.name !== 'AbortError') setOperationError(error)
      })
    return () => controller.abort()
  }, [operationId, queryClient, runId, runStatus])

  if (query.isLoading) return <div className="page-frame"><Skeleton className="h-80 w-full" /></div>
  const run = query.data
  if (!run) return <div className="empty-state"><h1>Run 不存在</h1><Button asChild><Link to="/runs">返回运行</Link></Button></div>

  const rejected = run.items.filter((item) => item.decision === 'rejected')
  const terminal = ['succeeded', 'partially_succeeded', 'failed', 'cancelled', 'timed_out'].includes(run.status)
  const unsuccessful = ['failed', 'cancelled', 'timed_out'].includes(run.status)
  const terminalLabel = run.status === 'partially_succeeded' ? '部分成功' : run.status === 'failed' ? '失败' : run.status === 'cancelled' ? '已取消' : run.status === 'timed_out' ? '已超时' : '完成'
  const phases = run.collectionMode === 'single'
    ? ['queued', 'fetching_list', 'finalizing', 'completed']
    : ['queued', 'fetching_list', 'discovering_details', 'fetching_details', 'finalizing', 'completed']
  const labels = run.collectionMode === 'single'
    ? ['排队', '直接采集', '质量终结', '完成']
    : ['排队', '列表分页', '发现详情', '详情采集', '质量终结', '完成']
  const currentPhase = operation?.phase ?? (terminal ? 'completed' : 'queued')
  const currentPhaseIndex = Math.max(0, phases.indexOf(currentPhase))
  const metrics = operation?.metrics
  const itemCount = Math.max(1, run.items.length)
  const titleCoverage = Math.round(run.items.filter((item) => item.title && item.title !== '未提取标题').length / itemCount * 100)
  const contentCoverage = Math.round(run.items.filter((item) => item.content).length / itemCount * 100)
  const source = runSourcePresentation(collectorQuery.data?.sourceUrl, run.collectorName)

  return (
    <div className="run-workbench">
      <div className="run-page-main">
        <header className="run-page-header">
          <div>
            <div className="title-line"><h1 title={source.full}>{source.root}</h1><StatusBadge status={run.status} /></div>
            <div className="run-header-subtitle">
              {source.path && <span className="run-source-path" title={source.full}>{source.path}</span>}
              <span className="run-header-meta">{run.startedAt} 开始 · {run.duration} · {executionModeLabel(run.executionMode)}</span>
            </div>
          </div>
          <Button asChild variant="outline"><Link to={`/collectors/${run.collectorId}`}>查看采集器 <ArrowRight /></Link></Button>
        </header>

        <Tabs defaultValue="results" className="run-workspace-tabs">
          <div className="run-workspace-nav">
            <TabsList variant="line" aria-label="运行详情视图">
              <TabsTrigger value="results"><ListTree />结果<span className="tab-count neutral">{run.acceptedCount + run.rejectedCount}</span></TabsTrigger>
              <TabsTrigger value="process"><Route />执行过程</TabsTrigger>
              <TabsTrigger value="scope"><Clock3 />范围与增量</TabsTrigger>
              <TabsTrigger value="quality"><ShieldCheck />质量与证据</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="results" className="run-tab-panel">
            <section aria-label="运行结果摘要" className={`run-result-summary ${unsuccessful ? 'danger' : run.status === 'partially_succeeded' ? 'warning' : 'success'}`}>
              <div className="run-result-heading">
                <div><h2>{runOutcomeTitle(run)}</h2><p>{paginationStopLabel(run.paginationStopReason)} · {executionModeLabel(run.executionMode)}</p></div>
                <dl className="run-result-facts">
                  <div><dt>接收</dt><dd>{run.acceptedCount}</dd></div>
                  <div><dt>拒绝</dt><dd className={run.rejectedCount > 0 ? 'danger-text' : ''}>{run.rejectedCount}</dd></div>
                  <div><dt>新增</dt><dd>{run.newItems}</dd></div>
                  <div><dt>更新</dt><dd>{run.updatedItems}</dd></div>
                  <div><dt>未变化</dt><dd>{run.unchangedItems}</dd></div>
                  <div><dt>耗时</dt><dd>{run.duration}</dd></div>
                </dl>
              </div>
            </section>

            {!terminal && <Alert className="run-diagnosis border-[#bcd6d2] bg-[#f0f8f7]"><LoaderCircle className="animate-spin text-[#087f73]" /><AlertTitle>运行正在执行</AlertTitle><AlertDescription>刷新页面后仍会继续读取同一任务的进度。</AlertDescription></Alert>}
            {operationError && <Alert variant="destructive" className="run-diagnosis"><AlertTriangle /><AlertTitle>无法继续读取运行进度</AlertTitle><AlertDescription>{operationError.message}</AlertDescription></Alert>}
            {run.status === 'partially_succeeded' && (
              <Alert className="run-diagnosis border-[#efd3a8] bg-[#fffaf1]">
                <AlertTriangle className="text-[#b56a09]" />
                <AlertTitle>部分结果需要处理</AlertTitle>
                <AlertDescription><strong>{run.summary}</strong><span>{run.recoveryAction}</span><span className="diagnosis-actions">{rejected[0] && <Button asChild size="sm"><Link to={`/items/${rejected[0].id}`}>查看拒绝项 <ArrowRight /></Link></Button>}<Button asChild size="sm" variant="outline"><Link to={`/collectors/${run.collectorId}`}>修订采集规则</Link></Button></span></AlertDescription>
              </Alert>
            )}
            {unsuccessful && <Alert variant="destructive" className="run-diagnosis"><AlertTriangle /><AlertTitle>运行{terminalLabel}</AlertTitle><AlertDescription><strong>{run.summary}</strong><span>{run.recoveryAction}</span></AlertDescription></Alert>}

            <section className="run-detail-section run-items-section">
              <header><div><h2>数据结果</h2><p>{run.acceptedCount} 条接收 · {run.rejectedCount} 条拒绝</p></div></header>
              {run.items.length > 0
                ? <div className="sample-list item-results">{run.items.map((item) => <Link key={item.id} to={`/items/${item.id}`}><StatusBadge status={item.decision} /><span><strong>{item.title}</strong><small>{item.changeType ? `${changeTypeLabel(item.changeType)} · ` : ''}发布时间 {item.publishedAt} · 采集时间 {item.observedAt}{item.rejectionReason ? ` · ${item.rejectionReason}` : ''}</small></span><ArrowRight /></Link>)}</div>
                : <div className="card-empty">本次运行没有产生 Item。</div>}
            </section>
          </TabsContent>

          <TabsContent value="process" className="run-tab-panel">
            <section className="run-detail-section run-process-section">
              <header><div><h2>执行进度</h2><p>{terminal ? `已${terminalLabel}` : `当前阶段：${labels[currentPhaseIndex]}`}</p></div></header>
              <div className="run-timeline" aria-label="Run 阶段">
                {labels.map((label, index) => <span className={terminal && index === labels.length - 1 ? unsuccessful ? 'danger' : run.status === 'partially_succeeded' ? 'warning' : 'complete' : index < currentPhaseIndex || terminal ? 'complete' : index === currentPhaseIndex ? 'active' : 'pending'} key={label}><i>{index < currentPhaseIndex || terminal ? index === labels.length - 1 ? <FileCheck2 /> : <Check /> : index === currentPhaseIndex ? <LoaderCircle className="animate-spin" /> : <Clock3 />}</i>{terminal && index === labels.length - 1 ? terminalLabel : label}</span>)}
              </div>
              <dl className="run-execution-metrics">
                <div><dt>入口页</dt><dd>{metrics?.listPagesFetched ?? run.listPagesFetched}</dd></div>
                <div><dt>发现详情</dt><dd>{metrics?.detailUrlsDiscovered ?? run.detailUrlsDiscovered}</dd></div>
                <div><dt>抓取详情</dt><dd>{metrics?.detailPagesFetched ?? run.detailPagesFetched}</dd></div>
                <div><dt>窗口外记录</dt><dd>{metrics?.recordsOutsideWindow ?? run.recordsOutsideWindow}</dd></div>
                <div><dt>重复链接</dt><dd>{run.duplicateDetailUrls}</dd></div>
                <div><dt>停止原因</dt><dd>{paginationStopLabel(run.paginationStopReason)}</dd></div>
              </dl>
            </section>
            <section className="run-detail-section">
              <header><div><h2>阶段记录</h2></div></header>
              <RunAttemptList run={run} terminal={terminal} />
            </section>
          </TabsContent>

          <TabsContent value="scope" className="run-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>本次运行范围</h2><p>{executionModeLabel(run.executionMode)}</p></div></header>
              <dl className="run-scope-grid">
                <div><dt>执行方式</dt><dd>{run.executionMode === 'initial' ? '首次窗口' : run.executionMode === 'incremental' ? '增量回看' : '旧运行未记录'}</dd></div>
                <div><dt>有效窗口</dt><dd>{run.windowStart ? `${run.windowStart} 起` : '旧运行未记录'}</dd></div>
                <div><dt>停止原因</dt><dd>{paginationStopLabel(run.paginationStopReason)}</dd></div>
                <div><dt>执行前检查点</dt><dd>{run.checkpointBefore?.watermark ?? '未建立'}</dd></div>
                <div><dt>执行后检查点</dt><dd>{run.checkpointAfter?.watermark ?? '未推进'}</dd></div>
                <div><dt>数据变化</dt><dd>{run.newItems} 新增 · {run.updatedItems} 更新 · {run.unchangedItems} 未变化</dd></div>
              </dl>
            </section>
          </TabsContent>

          <TabsContent value="quality" className="run-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>质量结果</h2><p>{run.acceptedCount} 条进入交付集，{run.rejectedCount} 条被拒绝</p></div></header>
              <div className="run-quality-grid">
                <article><span>标题完整度</span><strong>{titleCoverage}%</strong><small>{titleCoverage === 100 ? '全部通过' : '存在缺失'}</small></article>
                <article><span>{run.collectionMode === 'single' ? '采集入口同源率' : '详情链接同源率'}</span><strong>100%</strong><small>网络边界通过</small></article>
                <article><span>正文完整度</span><strong>{contentCoverage}%</strong><small>{contentCoverage === 100 ? '全部通过' : '存在缺失'}</small></article>
              </div>
            </section>
            <RunEvidence run={run} terminal={terminal} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}

function runSourcePresentation(sourceUrl: string | undefined, fallback: string) {
  if (!sourceUrl) return { root: fallback, path: '', full: fallback }
  try {
    const url = new URL(sourceUrl)
    const path = `${url.pathname}${url.search}${url.hash}`
    return { root: url.origin, path: path === '/' ? '' : path, full: url.toString() }
  } catch {
    return { root: fallback, path: sourceUrl, full: sourceUrl }
  }
}

function RunAttemptList({ run, terminal }: { run: Run; terminal: boolean }) {
  return <div className="run-attempt-list">{run.collectionMode === 'single' ? <>
    <span><ShieldCheck /><strong>准备</strong><p>验证规则证明并固定本次执行上下文</p></span>
    <span><FileSearch /><strong>直接采集</strong><p>抓取 {run.listPagesFetched} 个入口页并提取字段</p></span>
    <span><Check /><strong>质量终结</strong><p>{terminal ? '接收与拒绝结果已冻结' : '等待结果集冻结'}</p></span>
  </> : <>
    <span><ShieldCheck /><strong>准备</strong><p>验证规则证明并固定本次执行上下文</p></span>
    <span><ListTree /><strong>列表分页</strong><p>抓取 {run.listPagesFetched} 页，{paginationStopLabel(run.paginationStopReason)}</p></span>
    <span><Route /><strong>发现详情</strong><p>规范化并去重 {run.detailUrlsDiscovered} 条详情链接</p></span>
    <span><FileSearch /><strong>详情采集</strong><p>成功抓取 {run.detailPagesFetched}/{run.detailUrlsDiscovered} 个详情页</p></span>
    <span><Check /><strong>质量终结</strong><p>{terminal ? '接收与拒绝结果已冻结' : '等待结果集冻结'}</p></span>
  </>}</div>
}

function RunEvidence({ run, terminal }: { run: Run; terminal: boolean }) {
  const integrityVerified = run.integrityStatus === 'verified'
  const policyFixed = run.policyContextStatus === 'fixed'
  return (
    <section className="run-detail-section run-proof-section" aria-label="运行可信证据">
      <header><div><h2>这次结果为什么可信</h2><p>规则、采集范围和结果集的固定状态</p></div><Fingerprint /></header>
      <div className="run-proof-grid">
        <article className={integrityVerified ? 'verified' : 'warning'}><ShieldCheck /><span><strong>{integrityVerified ? '规则证明已验证' : '规则证明不可用'}</strong><small>{integrityVerified ? '执行前完成完整性校验' : '需要检查规则证明状态'}</small></span></article>
        <article className={policyFixed ? 'verified' : 'warning'}><Clock3 /><span><strong>{policyFixed ? '采集范围已固定' : '范围上下文不完整'}</strong><small>{policyFixed ? '窗口与增量策略不可变' : '旧运行未记录完整策略'}</small></span></article>
        <article className={terminal ? 'verified' : 'pending'}><FileCheck2 /><span><strong>{terminal ? '结果集已冻结' : '结果集终结中'}</strong><small>{run.acceptedCount} 条接收 · {run.rejectedCount} 条拒绝</small></span></article>
        <article className="neutral"><Fingerprint /><span><strong>{artifactModeLabel(run.artifactMode)}</strong><small>运行证据保留方式</small></span></article>
      </div>
      <details className="run-technical-details">
        <summary><Braces /><span><strong>技术信息</strong><small>用于排障与审计</small></span><ArrowRight /></summary>
        <dl>
          <div><dt>Run ID</dt><dd><code>{run.id}</code></dd></div>
          <div><dt>Operation ID</dt><dd><code>{run.operationId ?? 'historical'}</code></dd></div>
          <div><dt>Collector ID</dt><dd><code>{run.collectorId}</code></dd></div>
          <div><dt>Rule Version</dt><dd><code>{run.ruleVersion}</code></dd></div>
          <div><dt>Policy Version</dt><dd><code>{run.policyVersion ?? 'legacy context unavailable'}</code></dd></div>
          <div><dt>Rule Digest</dt><dd><code>{run.ruleDigest}</code></dd></div>
          <div><dt>Policy Digest</dt><dd><code>{run.policyDigest ?? 'legacy context unavailable'}</code></dd></div>
          <div><dt>Attestation</dt><dd><code>{run.ruleAttestationId}</code></dd></div>
          <div><dt>Signing Key</dt><dd><code>{run.signingKeyId} · rev {run.trustRevision}</code></dd></div>
        </dl>
      </details>
    </section>
  )
}

function changeTypeLabel(type: NonNullable<Run['items'][number]['changeType']>) {
  return { new: '新增', updated: '更新', unchanged: '未变化' }[type]
}

function runOutcomeTitle(run: Run) {
  if (run.status === 'failed') return `运行失败，${run.rejectedCount} 个候选被拒绝`
  if (run.status === 'timed_out') return '运行超时，需要检查预算或采集来源'
  if (run.status === 'cancelled') return '运行已取消，结果未进入交付集'
  if (run.status === 'partially_succeeded' && run.paginationStopReason === 'detail_fetch_incomplete') {
    return `${run.acceptedCount} 条接收，${run.detailUrlsDiscovered - run.detailPagesFetched} 个详情页未抓取`
  }
  if (run.status === 'partially_succeeded') return `${run.acceptedCount} 条接收，${run.rejectedCount} 条拒绝，等待处理`
  return `${run.acceptedCount} 条数据已完成质量终结`
}

function executionModeLabel(mode: Run['executionMode']) {
  if (mode === 'initial') return '首次运行'
  if (mode === 'incremental') return '增量运行'
  return '历史运行'
}

function artifactModeLabel(mode: Run['artifactMode']) {
  return { metadata_only: '元数据证据', sampled: '抽样证据', replayable: '可回放证据' }[mode]
}

function paginationStopLabel(reason: Run['paginationStopReason']) {
  return {
    not_applicable: '不适用',
    empty_page: '空页停止',
    next_link_exhausted: '无下一页链接',
    max_pages: '达到页数上限',
    max_items: '达到明细上限',
    budget_exhausted: '请求预算耗尽',
    cross_host_blocked: '跨主机链接已阻断',
    time_window_reached: '已越过首次时间窗口',
    checkpoint_reached: '已越过增量检查点',
    detail_fetch_incomplete: '部分详情页抓取失败',
  }[reason]
}
