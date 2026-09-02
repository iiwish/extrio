import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { AlertTriangle, ArrowRight, Braces, Check, Clock3, FileCheck2, FileSearch, Fingerprint, ListTree, LoaderCircle, Route, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { api, waitForOperation } from '@/api/client'
import type { Operation, Run } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function RunPage() {
  const { t } = useTranslation('runs')
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
  if (!run) return <div className="empty-state"><h1>{t('detail.notFound')}</h1><Button asChild><Link to="/runs">{t('detail.backToRuns')}</Link></Button></div>

  const rejected = run.items.filter((item) => item.decision === 'rejected')
  const terminal = ['succeeded', 'partially_succeeded', 'failed', 'cancelled', 'timed_out'].includes(run.status)
  const unsuccessful = ['failed', 'cancelled', 'timed_out'].includes(run.status)
  const terminalLabel = run.status === 'partially_succeeded' ? t('detail.terminal.partially_succeeded') : run.status === 'failed' ? t('detail.terminal.failed') : run.status === 'cancelled' ? t('detail.terminal.cancelled') : run.status === 'timed_out' ? t('detail.terminal.timed_out') : t('detail.terminal.succeeded')
  const phases = run.collectionMode === 'single'
    ? ['queued', 'fetching_list', 'finalizing', 'completed']
    : ['queued', 'fetching_list', 'discovering_details', 'fetching_details', 'finalizing', 'completed']
  const labels = run.collectionMode === 'single'
    ? [t('detail.timeline.queued'), t('detail.timeline.directFetch'), t('detail.timeline.finalize'), t('detail.timeline.completed')]
    : [t('detail.timeline.queued'), t('detail.timeline.listPages'), t('detail.timeline.discoverDetails'), t('detail.timeline.fetchDetails'), t('detail.timeline.finalize'), t('detail.timeline.completed')]
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
              <span className="run-header-meta">{t('detail.headerMeta', { started: run.startedAt, duration: run.duration, mode: executionModeLabel(t, run.executionMode) })}</span>
            </div>
          </div>
          <Button asChild variant="outline"><Link to={`/collectors/${run.collectorId}`}>{t('detail.viewCollector')} <ArrowRight /></Link></Button>
        </header>

        <Tabs defaultValue="results" className="run-workspace-tabs">
          <div className="run-workspace-nav">
            <TabsList variant="line" aria-label={t('detail.tabsAria')}>
              <TabsTrigger value="results"><ListTree />{t('detail.tab.results')}<span className="tab-count neutral">{run.acceptedCount + run.rejectedCount}</span></TabsTrigger>
              <TabsTrigger value="process"><Route />{t('detail.tab.process')}</TabsTrigger>
              <TabsTrigger value="scope"><Clock3 />{t('detail.tab.scope')}</TabsTrigger>
              <TabsTrigger value="quality"><ShieldCheck />{t('detail.tab.quality')}</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="results" className="run-tab-panel">
            <section aria-label={t('detail.summaryAria')} className={`run-result-summary ${unsuccessful ? 'danger' : run.status === 'partially_succeeded' ? 'warning' : 'success'}`}>
              <div className="run-result-heading">
                <div><h2>{runOutcomeTitle(t, run)}</h2><p>{paginationStopLabel(t, run.paginationStopReason)} · {executionModeLabel(t, run.executionMode)}</p></div>
                <dl className="run-result-facts">
                  <div><dt>{t('detail.facts.accepted')}</dt><dd>{run.acceptedCount}</dd></div>
                  <div><dt>{t('detail.facts.rejected')}</dt><dd className={run.rejectedCount > 0 ? 'danger-text' : ''}>{run.rejectedCount}</dd></div>
                  <div><dt>{t('detail.facts.new')}</dt><dd>{run.newItems}</dd></div>
                  <div><dt>{t('detail.facts.updated')}</dt><dd>{run.updatedItems}</dd></div>
                  <div><dt>{t('detail.facts.unchanged')}</dt><dd>{run.unchangedItems}</dd></div>
                  <div><dt>{t('detail.facts.duration')}</dt><dd>{run.duration}</dd></div>
                </dl>
              </div>
            </section>

            {!terminal && <Alert className="run-diagnosis border-[#bcd6d2] bg-[#f0f8f7]"><LoaderCircle className="animate-spin text-[#087f73]" /><AlertTitle>{t('detail.runningTitle')}</AlertTitle><AlertDescription>{t('detail.runningDesc')}</AlertDescription></Alert>}
            {operationError && <Alert variant="destructive" className="run-diagnosis"><AlertTriangle /><AlertTitle>{t('detail.progressErrorTitle')}</AlertTitle><AlertDescription>{operationError.message}</AlertDescription></Alert>}
            {run.status === 'partially_succeeded' && (
              <Alert className="run-diagnosis border-[#efd3a8] bg-[#fffaf1]">
                <AlertTriangle className="text-[#b56a09]" />
                <AlertTitle>{t('detail.partialTitle')}</AlertTitle>
                <AlertDescription><strong>{run.summary}</strong><span>{run.recoveryAction}</span><span className="diagnosis-actions">{rejected[0] && <Button asChild size="sm"><Link to={`/items/${rejected[0].id}`}>{t('detail.viewRejected')} <ArrowRight /></Link></Button>}<Button asChild size="sm" variant="outline"><Link to={`/collectors/${run.collectorId}`}>{t('detail.reviseRule')}</Link></Button></span></AlertDescription>
              </Alert>
            )}
            {unsuccessful && <Alert variant="destructive" className="run-diagnosis"><AlertTriangle /><AlertTitle>{t('detail.unsuccessfulTitle', { status: terminalLabel })}</AlertTitle><AlertDescription><strong>{run.summary}</strong><span>{run.recoveryAction}</span></AlertDescription></Alert>}

            <section className="run-detail-section run-items-section">
              <header><div><h2>{t('detail.itemsHeading')}</h2><p>{t('detail.acceptedRejected', { accepted: run.acceptedCount, rejected: run.rejectedCount })}</p></div></header>
              {run.items.length > 0
                ? <div className="sample-list item-results">{run.items.map((item) => <Link key={item.id} to={`/items/${item.id}`}><StatusBadge status={item.decision} /><span><strong>{item.title}</strong><small>{item.changeType ? `${changeTypeLabel(t, item.changeType)} · ` : ''}{t('detail.itemMeta', { published: item.publishedAt, observed: item.observedAt })}{item.rejectionReason ? ` · ${item.rejectionReason}` : ''}</small></span><ArrowRight /></Link>)}</div>
                : <div className="card-empty">{t('detail.noItems')}</div>}
            </section>
          </TabsContent>

          <TabsContent value="process" className="run-tab-panel">
            <section className="run-detail-section run-process-section">
              <header><div><h2>{t('detail.processHeading')}</h2><p>{terminal ? t('detail.progressDone', { status: terminalLabel }) : t('detail.progressCurrent', { phase: labels[currentPhaseIndex] })}</p></div></header>
              <div className="run-timeline" aria-label={t('detail.timelineAria')}>
                {labels.map((label, index) => <span className={terminal && index === labels.length - 1 ? unsuccessful ? 'danger' : run.status === 'partially_succeeded' ? 'warning' : 'complete' : index < currentPhaseIndex || terminal ? 'complete' : index === currentPhaseIndex ? 'active' : 'pending'} key={label}><i>{index < currentPhaseIndex || terminal ? index === labels.length - 1 ? <FileCheck2 /> : <Check /> : index === currentPhaseIndex ? <LoaderCircle className="animate-spin" /> : <Clock3 />}</i>{terminal && index === labels.length - 1 ? terminalLabel : label}</span>)}
              </div>
              <dl className="run-execution-metrics">
                <div><dt>{t('detail.metrics.entryPages')}</dt><dd>{metrics?.listPagesFetched ?? run.listPagesFetched}</dd></div>
                <div><dt>{t('detail.metrics.detailsDiscovered')}</dt><dd>{metrics?.detailUrlsDiscovered ?? run.detailUrlsDiscovered}</dd></div>
                <div><dt>{t('detail.metrics.detailsFetched')}</dt><dd>{metrics?.detailPagesFetched ?? run.detailPagesFetched}</dd></div>
                <div><dt>{t('detail.metrics.outsideWindow')}</dt><dd>{metrics?.recordsOutsideWindow ?? run.recordsOutsideWindow}</dd></div>
                <div><dt>{t('detail.metrics.duplicateLinks')}</dt><dd>{run.duplicateDetailUrls}</dd></div>
                <div><dt>{t('detail.metrics.stopReason')}</dt><dd>{paginationStopLabel(t, run.paginationStopReason)}</dd></div>
              </dl>
            </section>
            <section className="run-detail-section">
              <header><div><h2>{t('detail.attemptsHeading')}</h2></div></header>
              <RunAttemptList run={run} terminal={terminal} />
            </section>
          </TabsContent>

          <TabsContent value="scope" className="run-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>{t('detail.scopeHeading')}</h2><p>{executionModeLabel(t, run.executionMode)}</p></div></header>
              <dl className="run-scope-grid">
                <div><dt>{t('detail.scope.executionMode')}</dt><dd>{run.executionMode === 'initial' ? t('detail.scope.modeInitial') : run.executionMode === 'incremental' ? t('detail.scope.modeIncremental') : t('detail.scope.modeLegacy')}</dd></div>
                <div><dt>{t('detail.scope.window')}</dt><dd>{run.windowStart ? t('detail.scope.windowFrom', { watermark: run.windowStart }) : t('detail.scope.notRecorded')}</dd></div>
                <div><dt>{t('detail.scope.stopReason')}</dt><dd>{paginationStopLabel(t, run.paginationStopReason)}</dd></div>
                <div><dt>{t('detail.scope.checkpointBefore')}</dt><dd>{run.checkpointBefore?.watermark ?? t('detail.scope.checkpointNotSet')}</dd></div>
                <div><dt>{t('detail.scope.checkpointAfter')}</dt><dd>{run.checkpointAfter?.watermark ?? t('detail.scope.checkpointNotAdvanced')}</dd></div>
                <div><dt>{t('detail.scope.change')}</dt><dd>{t('detail.scope.changeValue', { added: run.newItems, updated: run.updatedItems, unchanged: run.unchangedItems })}</dd></div>
              </dl>
            </section>
          </TabsContent>

          <TabsContent value="quality" className="run-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>{t('detail.qualityHeading')}</h2><p>{t('detail.qualitySummary', { accepted: run.acceptedCount, rejected: run.rejectedCount })}</p></div></header>
              <div className="run-quality-grid">
                <article><span>{t('detail.quality.titleCoverage')}</span><strong>{titleCoverage}%</strong><small>{titleCoverage === 100 ? t('detail.quality.allPass') : t('detail.quality.hasMissing')}</small></article>
                <article><span>{run.collectionMode === 'single' ? t('detail.quality.entryHomogeneity') : t('detail.quality.detailHomogeneity')}</span><strong>100%</strong><small>{t('detail.quality.networkBoundaryPass')}</small></article>
                <article><span>{t('detail.quality.contentCoverage')}</span><strong>{contentCoverage}%</strong><small>{contentCoverage === 100 ? t('detail.quality.allPass') : t('detail.quality.hasMissing')}</small></article>
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
  const { t } = useTranslation('runs')
  return <div className="run-attempt-list">{run.collectionMode === 'single' ? <>
    <span><ShieldCheck /><strong>{t('detail.stage.prepare')}</strong><p>{t('detail.stage.prepareDesc')}</p></span>
    <span><FileSearch /><strong>{t('detail.stage.directFetch')}</strong><p>{t('detail.stage.directFetchDesc', { count: run.listPagesFetched })}</p></span>
    <span><Check /><strong>{t('detail.stage.finalize')}</strong><p>{terminal ? t('detail.stage.finalizedDesc') : t('detail.stage.finalizingDesc')}</p></span>
  </> : <>
    <span><ShieldCheck /><strong>{t('detail.stage.prepare')}</strong><p>{t('detail.stage.prepareDesc')}</p></span>
    <span><ListTree /><strong>{t('detail.stage.listPages')}</strong><p>{t('detail.stage.listPagesDesc', { count: run.listPagesFetched, reason: paginationStopLabel(t, run.paginationStopReason) })}</p></span>
    <span><Route /><strong>{t('detail.stage.discoverDetails')}</strong><p>{t('detail.stage.discoverDetailsDesc', { count: run.detailUrlsDiscovered })}</p></span>
    <span><FileSearch /><strong>{t('detail.stage.fetchDetails')}</strong><p>{t('detail.stage.fetchDetailsDesc', { fetched: run.detailPagesFetched, discovered: run.detailUrlsDiscovered })}</p></span>
    <span><Check /><strong>{t('detail.stage.finalize')}</strong><p>{terminal ? t('detail.stage.finalizedDesc') : t('detail.stage.finalizingDesc')}</p></span>
  </>}</div>
}

function RunEvidence({ run, terminal }: { run: Run; terminal: boolean }) {
  const { t } = useTranslation('runs')
  const integrityVerified = run.integrityStatus === 'verified'
  const policyFixed = run.policyContextStatus === 'fixed'
  return (
    <section className="run-detail-section run-proof-section" aria-label={t('detail.evidenceAria')}>
      <header><div><h2>{t('detail.proofHeading')}</h2><p>{t('detail.proofSub')}</p></div><Fingerprint /></header>
      <div className="run-proof-grid">
        <article className={integrityVerified ? 'verified' : 'warning'}><ShieldCheck /><span><strong>{integrityVerified ? t('detail.proof.integrityVerified') : t('detail.proof.integrityUnavailable')}</strong><small>{integrityVerified ? t('detail.proof.integrityVerifiedDesc') : t('detail.proof.integrityUnavailableDesc')}</small></span></article>
        <article className={policyFixed ? 'verified' : 'warning'}><Clock3 /><span><strong>{policyFixed ? t('detail.proof.scopeFixed') : t('detail.proof.scopeIncomplete')}</strong><small>{policyFixed ? t('detail.proof.scopeFixedDesc') : t('detail.proof.scopeIncompleteDesc')}</small></span></article>
        <article className={terminal ? 'verified' : 'pending'}><FileCheck2 /><span><strong>{terminal ? t('detail.proof.frozen') : t('detail.proof.finalizing')}</strong><small>{t('detail.acceptedRejected', { accepted: run.acceptedCount, rejected: run.rejectedCount })}</small></span></article>
        <article className="neutral"><Fingerprint /><span><strong>{artifactModeLabel(t, run.artifactMode)}</strong><small>{t('detail.proof.artifactModeDesc')}</small></span></article>
      </div>
      <details className="run-technical-details">
        <summary><Braces /><span><strong>{t('detail.technical.heading')}</strong><small>{t('detail.technical.sub')}</small></span><ArrowRight /></summary>
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

function changeTypeLabel(t: TFunction, type: NonNullable<Run['items'][number]['changeType']>) {
  return { new: t('detail.change.new'), updated: t('detail.change.updated'), unchanged: t('detail.change.unchanged') }[type]
}

function runOutcomeTitle(t: TFunction, run: Run) {
  if (run.status === 'failed') return t('detail.outcome.failed', { count: run.rejectedCount })
  if (run.status === 'timed_out') return t('detail.outcome.timedOut')
  if (run.status === 'cancelled') return t('detail.outcome.cancelled')
  if (run.status === 'partially_succeeded' && run.paginationStopReason === 'detail_fetch_incomplete') {
    return t('detail.outcome.detailIncomplete', { accepted: run.acceptedCount, missing: run.detailUrlsDiscovered - run.detailPagesFetched })
  }
  if (run.status === 'partially_succeeded') return t('detail.outcome.partial', { accepted: run.acceptedCount, rejected: run.rejectedCount })
  return t('detail.outcome.succeeded', { count: run.acceptedCount })
}

function executionModeLabel(t: TFunction, mode: Run['executionMode']) {
  if (mode === 'initial') return t('detail.mode.initial')
  if (mode === 'incremental') return t('detail.mode.incremental')
  return t('detail.mode.historical')
}

function artifactModeLabel(t: TFunction, mode: Run['artifactMode']) {
  return { metadata_only: t('detail.proof.artifact.metadata_only'), sampled: t('detail.proof.artifact.sampled'), replayable: t('detail.proof.artifact.replayable') }[mode]
}

function paginationStopLabel(t: TFunction, reason: Run['paginationStopReason']) {
  return {
    not_applicable: t('detail.stopReason.not_applicable'),
    empty_page: t('detail.stopReason.empty_page'),
    next_link_exhausted: t('detail.stopReason.next_link_exhausted'),
    max_pages: t('detail.stopReason.max_pages'),
    max_items: t('detail.stopReason.max_items'),
    budget_exhausted: t('detail.stopReason.budget_exhausted'),
    cross_host_blocked: t('detail.stopReason.cross_host_blocked'),
    time_window_reached: t('detail.stopReason.time_window_reached'),
    checkpoint_reached: t('detail.stopReason.checkpoint_reached'),
    detail_fetch_incomplete: t('detail.stopReason.detail_fetch_incomplete'),
  }[reason]
}
