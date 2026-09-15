import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DeletedSourceBadge, HistoryAttribution } from '@/features/collectors/collector-management'
import type { TFunction } from 'i18next'
import { AlertTriangle, ArrowRight, Braces, Check, Clock3, FileCheck2, FileSearch, Fingerprint, ListTree, LoaderCircle, Route, ShieldCheck, Square, RotateCcw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useRef } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { Run } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DetailPanel } from '@/components/detail-panel'
import './run-detail.css'
import { QueryError } from '@/components/query-error'
import { useWorkspaceLink, useWorkspaceSection } from '@/lib/workspace-navigation'
import { runTimestamp } from '@/lib/content-presentation'

export function RunPage() {
  const { t, i18n } = useTranslation('runs')
  const workspaceLink = useWorkspaceLink()
  const [section, setSection] = useWorkspaceSection(['results','process','scope','quality'], 'results')
  const [params, setParams] = useSearchParams()
  const rejectedOnly = params.get('decision') === 'rejected'
  const resultsRef = useRef<HTMLHeadingElement>(null)
  const processTabRef = useRef<HTMLButtonElement>(null)
  function showExecution() {
    setSection('process')
    requestAnimationFrame(() => processTabRef.current?.focus())
  }
  function showResults(onlyRejected: boolean) {
    const next = new URLSearchParams(params)
    next.set('section', 'results')
    if (onlyRejected) next.set('decision', 'rejected'); else next.delete('decision')
    setParams(next)
    requestAnimationFrame(() => resultsRef.current?.focus())
  }
  const { runId = '' } = useParams()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const query = useQuery({ queryKey: ['run', runId], queryFn: () => api.runDetail(runId), refetchInterval: (query) => query.state.data && ['queued', 'running', 'finalizing'].includes(query.state.data.status) ? 2000 : false })
  const operationId = query.data?.operationId
  const operationQuery = useQuery({ queryKey: ['operation', operationId], queryFn: () => api.operation(operationId!), enabled: Boolean(operationId), refetchInterval: (query) => query.state.data && ['queued', 'running', 'finalizing'].includes(query.state.data.status) ? 2000 : false })
  const operation = operationQuery.data
  const cancelMutation = useMutation({ mutationFn: () => api.cancelOperation(operationId!), onSuccess: (result) => {
    queryClient.setQueryData(['operation', operationId], result)
    void queryClient.invalidateQueries({ queryKey: ['run', runId] })
    void queryClient.invalidateQueries({ queryKey: ['runs'] })
  } })
  const collectorId = query.data?.collectorId ?? ''
  const collectorQuery = useQuery({ queryKey: ['collector', collectorId], queryFn: () => api.collector(collectorId), enabled: Boolean(collectorId) && !query.data?.collectorDeleted })

  if (query.isLoading) return <div className="page-frame"><Skeleton className="h-80 w-full" /></div>
  const run = query.data
  if (!run && query.error) return <div className="page-frame"><QueryError error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} /></div>
  if (!run) return <div className="empty-state"><h1>{t('detail.notFound')}</h1><Button asChild><Link to="/runs">{t('detail.backToRuns')}</Link></Button></div>

  const rejected = run.items.filter((item) => item.decision === 'rejected')
  const visibleItems = rejectedOnly ? rejected : run.items
  const missingDetails = Math.max(0, run.detailUrlsDiscovered - run.detailPagesFetched)
  const pageLimitOnly = ['succeeded', 'partially_succeeded'].includes(run.status) && run.paginationStopReason === 'max_pages' && run.rejectedCount === 0 && missingDetails === 0
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
  const failureReason = operation?.error?.details?.reason
  const failureGroup = operation?.error?.code === 'SOURCE_NETWORK_REJECTED' ? sourceFailureGroup(String(failureReason ?? '')) : run.status === 'cancelled' ? 'cancelled' : run.status === 'timed_out' ? 'budget' : 'general'

  return (
    <div className="run-workbench">
      <div className="run-page-main">
        <QueryError error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
        <header className="run-page-header">
          <div>
            <div className="title-line"><h1 title={source.full}>{source.root}</h1><StatusBadge status={run.status} />{run.collectorDeleted && <DeletedSourceBadge />}</div>
            <div className="run-header-subtitle">
              {source.path && <span className="run-source-path" title={source.full}>{source.path}</span>}
              <span className="run-header-meta">{t('detail.headerMeta', { started: runTimestamp(run, i18n.language), duration: run.duration, mode: executionModeLabel(t, run.executionMode) })}</span>
            </div>
          </div>
          <div className="run-header-actions">
            {!terminal && operationId && ['administrator', 'engineer'].includes(user.role) && <Button variant="outline" disabled={cancelMutation.isPending || Boolean(operation?.cancelRequested)} onClick={() => cancelMutation.mutate()}><Square />{operation?.cancelRequested ? t('detail.cancelPending') : t('detail.cancel')}</Button>}
            {!run.collectorDeleted && <Button asChild variant="outline"><Link to={workspaceLink(`/collectors/${run.collectorId}`)}>{t('detail.viewCollector')} <ArrowRight /></Link></Button>}
          </div>
        </header>
        <HistoryAttribution value={run.collectionAttribution} />

        <Tabs value={section} onValueChange={setSection} className="run-workspace-tabs">
          <div className="run-workspace-nav">
            <TabsList variant="line" aria-label={t('detail.tabsAria')}>
              <TabsTrigger value="results"><ListTree />{t('detail.tab.results')}<span className="tab-count neutral">{run.acceptedCount + run.rejectedCount}</span></TabsTrigger>
              <TabsTrigger ref={processTabRef} value="process"><Route />{t('detail.tab.process')}</TabsTrigger>
              <TabsTrigger value="scope"><Clock3 />{t('detail.tab.scope')}</TabsTrigger>
              <TabsTrigger value="quality"><ShieldCheck />{t('detail.tab.quality')}</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="results" className="run-tab-panel">
            <DetailPanel aria-label={t('detail.summaryAria')} className={`run-result-summary ${unsuccessful ? 'danger' : run.status === 'partially_succeeded' ? 'warning' : 'success'}`}>
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
            </DetailPanel>

            {!terminal && <Alert className="run-diagnosis border-[#bcd6d2] bg-[#f0f8f7]"><LoaderCircle className="animate-spin text-[#087f73]" /><AlertTitle>{t('detail.runningTitle')}</AlertTitle><AlertDescription>{t('detail.runningDesc')}</AlertDescription></Alert>}
            <QueryError error={operationQuery.error} onRetry={() => void operationQuery.refetch()} retrying={operationQuery.isFetching} />
            {cancelMutation.error && <Alert variant="destructive" className="run-diagnosis"><AlertTriangle /><AlertDescription>{cancelMutation.error.message}</AlertDescription></Alert>}
            {pageLimitOnly && (
              <Alert className="run-diagnosis">
                <AlertTriangle />
                <AlertTitle>{t('detail.pageLimitTitle')}</AlertTitle>
                <AlertDescription><strong>{t('detail.pageLimitSummary', { accepted: run.acceptedCount, pages: run.listPagesFetched })}</strong><span>{t('detail.pageLimitHelp')}</span></AlertDescription>
              </Alert>
            )}
            {run.status === 'partially_succeeded' && !pageLimitOnly && (
              <Alert className="run-diagnosis border-[#efd3a8] bg-[#fffaf1]">
                <AlertTriangle className="text-[#b56a09]" />
                <AlertTitle>{t('detail.partialTitle')}</AlertTitle>
                <AlertDescription><strong>{run.summary}</strong>
                  {run.rejectedCount > 0 && <div className="run-issue-group"><strong>{t('detail.rejectedGroup', { count: run.rejectedCount })}</strong><span>{t('detail.rejectedHelp')}</span><span className="diagnosis-actions"><Button size="sm" onClick={() => showResults(true)}>{t('detail.viewRejected')}<ArrowRight /></Button>{!run.collectorDeleted && <Button asChild size="sm" variant="outline"><Link to={workspaceLink(`/collectors/${run.collectorId}?section=rule`)}>{t('detail.inspectRule')}</Link></Button>}</span></div>}
                  {missingDetails > 0 && <div className="run-issue-group"><strong>{t('detail.unfetchedGroup', { count: missingDetails })}</strong><span>{t('detail.unfetchedHelp')}</span><Button size="sm" variant="outline" onClick={showExecution}>{t('detail.inspectExecution')}<ArrowRight /></Button></div>}
                  {!missingDetails && !run.rejectedCount && <Button size="sm" variant="outline" onClick={showExecution}>{t('detail.inspectExecution')}<ArrowRight /></Button>}
                  {run.collectorDeleted && <span>{t('collectors:management.deletedNotice')}</span>}
                </AlertDescription>
              </Alert>
            )}
            {unsuccessful && <Alert variant="destructive" className="run-diagnosis"><AlertTriangle /><AlertTitle>{t('detail.unsuccessfulTitle', { status: terminalLabel })}</AlertTitle><AlertDescription><strong>{t(`detail.failure.${failureGroup}`)}</strong><span>{t(`detail.recovery.${failureGroup}`)}</span>{operation?.error?.code && <code>{operation.error.code}{typeof failureReason === 'string' ? ` · ${failureReason}` : ''}</code>}<Button size="sm" variant="outline" onClick={showExecution}>{t('detail.inspectExecution')}<ArrowRight /></Button>{failureGroup === 'structure' && !run.collectorDeleted && <Link to={workspaceLink(`/collectors/${run.collectorId}?section=rule`)}>{t('detail.inspectRule')}</Link>}</AlertDescription></Alert>}

            <DetailPanel className="run-detail-section run-items-section">
              <header><div><h2 ref={resultsRef} tabIndex={-1}>{t('detail.itemsHeading')}</h2><p>{t('detail.acceptedRejected', { accepted: run.acceptedCount, rejected: run.rejectedCount })}</p></div><div role="group" aria-label={t('detail.resultFilter')}><Button size="sm" variant={rejectedOnly ? 'ghost' : 'secondary'} aria-pressed={!rejectedOnly} onClick={() => showResults(false)}>{t('detail.allResults')}</Button><Button size="sm" variant={rejectedOnly ? 'secondary' : 'ghost'} aria-pressed={rejectedOnly} onClick={() => showResults(true)}>{t('detail.onlyRejected')}</Button></div></header>
              {rejectedOnly && rejected.length < run.rejectedCount && <p role="status">{t('detail.rejectedLoaded', { count: rejected.length, total: run.rejectedCount })}</p>}
              {visibleItems.length > 0
                ? <div className="sample-list item-results">{visibleItems.map((item) => <Link key={item.id} to={workspaceLink(`/items/${item.id}`)}><StatusBadge status={item.decision} /><span><strong>{item.title}</strong><small>{item.changeType ? `${changeTypeLabel(t, item.changeType)} · ` : ''}{t('detail.itemMeta', { published: item.publishedAt, observed: item.observedAt })}{item.rejectionReason ? ` · ${item.rejectionReason}` : ''}</small></span><ArrowRight /></Link>)}</div>
                : <div className="card-empty">{t(rejectedOnly ? run.rejectedCount > 0 ? 'detail.rejectedUnavailable' : 'detail.noRejected' : 'detail.noItems')}</div>}
            </DetailPanel>
          </TabsContent>

          <TabsContent value="process" className="run-tab-panel">
            <QueryError error={operationQuery.error} onRetry={() => void operationQuery.refetch()} retrying={operationQuery.isFetching} />
            {unsuccessful && <Alert variant="destructive"><AlertTriangle /><AlertTitle>{t('detail.unsuccessfulTitle', { status: terminalLabel })}</AlertTitle><AlertDescription><strong>{t(`detail.failure.${failureGroup}`)}</strong><span>{t(`detail.recovery.${failureGroup}`)}</span>{operation?.error?.code && <code>{operation.error.code}{typeof failureReason === 'string' ? ` · ${failureReason}` : ''}</code>}</AlertDescription></Alert>}
            <DetailPanel className="run-detail-section run-process-section">
              <header><div><h2>{t('detail.processHeading')}</h2><p>{terminal ? t('detail.progressDone', { status: terminalLabel }) : t('detail.progressCurrent', { phase: labels[currentPhaseIndex] })}</p></div></header>
              <div className="run-timeline" aria-label={t('detail.timelineAria')}>
                {labels.map((label, index) => {
                  const last = index === labels.length - 1
                  const complete = !unsuccessful && (index < currentPhaseIndex || terminal)
                  const active = !terminal && index === currentPhaseIndex
                  return <span className={terminal && last && unsuccessful ? 'danger' : terminal && last && run.status === 'partially_succeeded' ? 'warning' : complete ? 'complete' : active ? 'active' : 'pending'} key={label}><i>{terminal && last && unsuccessful ? <AlertTriangle /> : complete ? last ? <FileCheck2 /> : <Check /> : active ? <LoaderCircle className="animate-spin" /> : <Clock3 />}</i>{terminal && last ? terminalLabel : label}</span>
                })}
              </div>
              <dl className="run-execution-metrics">
                <div><dt>{t('detail.metrics.entryPages')}</dt><dd>{metrics?.listPagesFetched ?? run.listPagesFetched}</dd></div>
                <div><dt>{t('detail.metrics.detailsDiscovered')}</dt><dd>{metrics?.detailUrlsDiscovered ?? run.detailUrlsDiscovered}</dd></div>
                <div><dt>{t('detail.metrics.detailsFetched')}</dt><dd>{metrics?.detailPagesFetched ?? run.detailPagesFetched}</dd></div>
                <div><dt>{t('detail.metrics.outsideWindow')}</dt><dd>{metrics?.recordsOutsideWindow ?? run.recordsOutsideWindow}</dd></div>
                <div><dt>{t('detail.metrics.duplicateLinks')}</dt><dd>{run.duplicateDetailUrls}</dd></div>
                <div><dt>{t('detail.metrics.stopReason')}</dt><dd>{paginationStopLabel(t, run.paginationStopReason)}</dd></div>
              </dl>
            </DetailPanel>
            <DetailPanel className="run-detail-section">
              <header><div><h2>{t('detail.attemptsHeading')}</h2></div></header>
              <RunAttemptList run={run} terminal={terminal} />
            </DetailPanel>
          </TabsContent>

          <TabsContent value="scope" className="run-tab-panel">
            <DetailPanel className="run-detail-section">
              <header><div><h2>{t('detail.scopeHeading')}</h2><p>{executionModeLabel(t, run.executionMode)}</p></div></header>
              <dl className="run-scope-grid">
                <div><dt>{t('detail.scope.executionMode')}</dt><dd>{run.executionMode === 'initial' ? t('detail.scope.modeInitial') : run.executionMode === 'incremental' ? t('detail.scope.modeIncremental') : t('detail.scope.modeLegacy')}</dd></div>
                <div><dt>{t('detail.scope.window')}</dt><dd>{run.windowStart ? t('detail.scope.windowFrom', { watermark: run.windowStart }) : t('detail.scope.notRecorded')}</dd></div>
                <div><dt>{t('detail.scope.stopReason')}</dt><dd>{paginationStopLabel(t, run.paginationStopReason)}</dd></div>
                <div><dt>{t('detail.scope.checkpointBefore')}</dt><dd>{run.checkpointBefore?.watermark ?? t('detail.scope.checkpointNotSet')}</dd></div>
                <div><dt>{t('detail.scope.checkpointAfter')}</dt><dd>{run.checkpointAfter?.watermark ?? t('detail.scope.checkpointNotAdvanced')}</dd></div>
                <div><dt>{t('detail.scope.change')}</dt><dd>{t('detail.scope.changeValue', { added: run.newItems, updated: run.updatedItems, unchanged: run.unchangedItems })}</dd></div>
              </dl>
            </DetailPanel>
          </TabsContent>

          <TabsContent value="quality" className="run-tab-panel">
            <DetailPanel className="run-detail-section">
              <header><div><h2>{t('detail.qualityHeading')}</h2><p>{t('detail.qualitySummary', { accepted: run.acceptedCount, rejected: run.rejectedCount })}</p></div></header>
              <div className="run-quality-grid">
                <article><span>{t('detail.quality.titleCoverage')}</span><strong>{titleCoverage}%</strong><small>{titleCoverage === 100 ? t('detail.quality.allPass') : t('detail.quality.hasMissing')}</small></article>
                <article><span>{t('detail.metrics.detailsFetched')}</span><strong>{run.detailPagesFetched}</strong><small>{t('detail.actualFetchCount')}</small></article>
                <article><span>{t('detail.quality.contentCoverage')}</span><strong>{contentCoverage}%</strong><small>{contentCoverage === 100 ? t('detail.quality.allPass') : t('detail.quality.hasMissing')}</small></article>
              </div>
            </DetailPanel>
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
  const finalMessage = terminal && ['failed', 'cancelled', 'timed_out'].includes(run.status) ? t('detail.noCommit') : terminal ? t('detail.stage.finalizedDesc') : t('detail.stage.finalizingDesc')
  return <div className="run-attempt-list">{run.collectionMode === 'single' ? <>
    <span><ShieldCheck /><strong>{t('detail.stage.prepare')}</strong><p>{t('detail.stage.prepareDesc')}</p></span>
    <span><FileSearch /><strong>{t('detail.stage.directFetch')}</strong><p>{t('detail.stage.directFetchDesc', { count: run.detailPagesFetched })}</p></span>
    <span><Check /><strong>{t('detail.stage.finalize')}</strong><p>{finalMessage}</p></span>
  </> : <>
    <span><ShieldCheck /><strong>{t('detail.stage.prepare')}</strong><p>{t('detail.stage.prepareDesc')}</p></span>
    <span><ListTree /><strong>{t('detail.stage.listPages')}</strong><p>{t('detail.stage.listPagesDesc', { count: run.listPagesFetched, reason: paginationStopLabel(t, run.paginationStopReason) })}</p></span>
    <span><Route /><strong>{t('detail.stage.discoverDetails')}</strong><p>{t('detail.stage.discoverDetailsDesc', { count: run.detailUrlsDiscovered })}</p></span>
    <span><FileSearch /><strong>{t('detail.stage.fetchDetails')}</strong><p>{t('detail.stage.fetchDetailsDesc', { fetched: run.detailPagesFetched, discovered: run.detailUrlsDiscovered })}</p></span>
    <span><Check /><strong>{t('detail.stage.finalize')}</strong><p>{finalMessage}</p></span>
  </>}</div>
}

function RunEvidence({ run, terminal }: { run: Run; terminal: boolean }) {
  const { t } = useTranslation('runs')
  const evidenceQuery = useQuery({ queryKey: ['run-evidence', run.id, run.status], queryFn: () => api.runEvidence(run.id), refetchInterval: terminal ? false : 5000 })
  const evidence = evidenceQuery.data
  const integrityVerified = run.integrityStatus === 'verified'
  const policyFixed = run.policyContextStatus === 'fixed'
  const frozen = ['succeeded', 'partially_succeeded'].includes(run.status)
  return (
    <DetailPanel className="run-detail-section run-proof-section" aria-label={t('detail.evidenceAria')}>
      <header><div><h2>{t('detail.proofHeading')}</h2><p>{t('detail.proofSub')}</p></div><Fingerprint /></header>
      <div className="run-proof-grid">
        <article className={integrityVerified ? 'verified' : 'warning'}><ShieldCheck /><span><strong>{integrityVerified ? t('detail.proof.integrityVerified') : t('detail.proof.integrityUnavailable')}</strong><small>{integrityVerified ? t('detail.proof.integrityVerifiedDesc') : t('detail.proof.integrityUnavailableDesc')}</small></span></article>
        <article className={policyFixed ? 'verified' : 'warning'}><Clock3 /><span><strong>{policyFixed ? t('detail.proof.scopeFixed') : t('detail.proof.scopeIncomplete')}</strong><small>{policyFixed ? t('detail.proof.scopeFixedDesc') : t('detail.proof.scopeIncompleteDesc')}</small></span></article>
        <article className={frozen ? 'verified' : 'pending'}><FileCheck2 /><span><strong>{frozen ? t('detail.proof.frozen') : terminal ? t('detail.noCommit') : t('detail.proof.finalizing')}</strong><small>{t('detail.acceptedRejected', { accepted: run.acceptedCount, rejected: run.rejectedCount })}</small></span></article>
        <article className="neutral"><Fingerprint /><span><strong>{artifactModeLabel(t, evidence?.mode ?? 'metadata_only')}</strong><small>{evidence ? t(`detail.evidenceState.${evidence.state}`) : t('detail.checkingEvidence')}</small></span></article>
      </div>
      <QueryError error={evidenceQuery.error} onRetry={() => void evidenceQuery.refetch()} retrying={evidenceQuery.isFetching} />
      {evidence && <div className="run-evidence-availability"><span>{t('detail.evidenceFiles', { count: evidence.fileCount, bytes: evidence.totalBytes })}{evidence.expiresAt && <small>{t('detail.evidenceExpiry', { date: new Date(evidence.expiresAt).toLocaleString() })}</small>}</span><Button variant="outline" disabled title={t('detail.noReplay')}><RotateCcw />{t('detail.noReplay')}</Button></div>}
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
    </DetailPanel>
  )
}

function changeTypeLabel(t: TFunction, type: NonNullable<Run['items'][number]['changeType']>) {
  return { new: t('detail.change.new'), updated: t('detail.change.updated'), unchanged: t('detail.change.unchanged') }[type]
}

function runOutcomeTitle(t: TFunction, run: Run) {
  if (['succeeded', 'partially_succeeded'].includes(run.status) && run.paginationStopReason === 'max_pages' && run.rejectedCount === 0 && run.detailPagesFetched >= run.detailUrlsDiscovered) return t('detail.pageLimitOutcome', { accepted: run.acceptedCount })
  if (['queued', 'running', 'finalizing'].includes(run.status)) return t('detail.runningTitle')
  if (run.status === 'failed') return t('detail.outcome.failed', { count: run.rejectedCount })
  if (run.status === 'timed_out') return t('detail.outcome.timedOut')
  if (run.status === 'cancelled') return t('detail.outcome.cancelled')
  if (run.status === 'partially_succeeded' && run.paginationStopReason === 'detail_fetch_incomplete') {
    return t('detail.outcome.detailIncomplete', { accepted: run.acceptedCount, missing: run.detailUrlsDiscovered - run.detailPagesFetched })
  }
  if (run.status === 'partially_succeeded') return t('detail.outcome.partial', { accepted: run.acceptedCount, rejected: run.rejectedCount })
  return t('detail.outcome.succeeded', { count: run.acceptedCount })
}

function sourceFailureGroup(reason: string) {
  if (reason === 'source_structure_mismatch') return 'structure'
  if (['anonymous_get_only', 'request_query_unsupported'].includes(reason)) return 'unsupported'
  if (['authentication_or_access_required', 'robots_disallowed'].includes(reason)) return 'access'
  if (reason.includes('exceeded')) return 'budget'
  if (['host_not_allowed', 'network_address_blocked', 'https_required', 'redirect_https_downgrade'].includes(reason)) return 'boundary'
  return 'connection'
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
