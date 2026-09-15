import { useQuery } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { ArrowRight, Bot, Braces, Check, Clock3, FileCheck2, Fingerprint, ListChecks, LoaderCircle, MessageSquareText, Route, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { AiRunDetail, ModelInvocation, OperationActivity } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DetailPanel } from '@/components/detail-panel'
import './run-detail.css'
import './ai-run-detail.css'
import { QueryError } from '@/components/query-error'
import { useWorkspaceLink, useWorkspaceSection } from '@/lib/workspace-navigation'
import { DeletedSourceBadge, HistoryAttribution } from '@/features/collectors/collector-management'

export function AiRunPage() {
  const { t } = useTranslation('aiRuns')
  const { aiRunId = '' } = useParams()
  const workspaceLink = useWorkspaceLink()
  const query = useQuery({
    queryKey: ['ai-run', aiRunId],
    queryFn: () => api.aiRunDetail(aiRunId),
    refetchInterval: (current) => {
      const status = current.state.data?.status
      return status && ['queued', 'running', 'finalizing'].includes(status) ? 500 : false
    },
  })
  const [section, setSection] = useWorkspaceSection(['result','process','models','evidence'], ['queued','running','finalizing'].includes(query.data?.status ?? '') ? 'process' : 'result')

  if (query.isLoading) return <div className="page-frame"><Skeleton className="h-80 w-full" /></div>
  const run = query.data
  if (!run && query.error) return <div className="page-frame"><QueryError error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} /></div>
  if (!run) return <div className="empty-state"><h1>{t('detail.notFound')}</h1><Button asChild><Link to="/runs?view=ai">{t('detail.backToAiRuns')}</Link></Button></div>

  const source = sourcePresentation(run.sourceUrl, run.collectorName)
  const invocations = run.attempts.flatMap((attempt) => attempt.modelInvocations)
  const active = ['queued', 'running', 'finalizing'].includes(run.status)
  const failed = run.status === 'failed' || run.resultStatus === 'no_candidate'

  return <div className="run-workbench ai-run-workbench">
    <div className="run-page-main">
      <QueryError error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
      <header className="run-page-header ai-run-page-header">
        <div>
          <div className="title-line"><h1 title={source.full}>{source.root}</h1><AiRunState run={run} />{run.collectorDeleted && <DeletedSourceBadge />}</div>
          <div className="run-header-subtitle">
            {source.path && <span className="run-source-path" title={source.full}>{source.path}</span>}
            <span className="run-header-meta">{t('detail.headerMeta', { kind: taskKindLabel(t, run), started: formatDateTime(run.createdAt) })}</span>
          </div>
        </div>
        {!run.collectorDeleted && <Button asChild variant={run.reviewStatus === 'ready_review' ? 'default' : 'outline'}>
          <Link to={workspaceLink(`/collectors/${run.collectorId}${run.reviewStatus === 'ready_review' ? '?section=rule' : ''}`)}>
            {run.reviewStatus === 'ready_review' ? t('detail.reviewCandidate') : t('detail.viewCollector')} <ArrowRight />
          </Link>
        </Button>}
      </header>
      <HistoryAttribution value={run.collectionAttribution} />

      <Tabs value={section} onValueChange={setSection} className="run-workspace-tabs">
        <div className="run-workspace-nav">
          <TabsList variant="line" aria-label={t('detail.tabsAria')}>
            <TabsTrigger value="result"><Sparkles />{t('detail.tab.result')}</TabsTrigger>
            <TabsTrigger value="process"><Route />{t('detail.tab.process')}</TabsTrigger>
            <TabsTrigger value="models"><Bot />{t('detail.tab.models')}<span className="tab-count neutral">{invocations.length}</span></TabsTrigger>
            <TabsTrigger value="evidence"><ShieldCheck />{t('detail.tab.evidence')}</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="result" className="run-tab-panel">
          <AiRunSummary run={run} failed={failed} />
          <DetailPanel className="run-detail-section ai-result-section">
            <header><div><h2>{t('detail.outputHeading')}</h2><p>{resultDescription(t, run)}</p></div>{!run.collectorDeleted && run.reviewStatus === 'ready_review' && <Badge variant="outline" className="ai-review-badge">{t('detail.awaitingReview')}</Badge>}</header>
            <dl className="ai-result-grid">
              <div><dt>{t('detail.facts.attempts')}</dt><dd>{run.attemptCount}</dd></div>
              <div><dt>{t('detail.facts.reviewStatus')}</dt><dd>{reviewLabel(t, run.reviewStatus, run.collectorDeleted)}</dd></div>
            </dl>
            {failed && <div className="ai-run-error"><TriangleAlert /><span><strong>{t('detail.noCandidateTitle')}</strong><small>{run.error ? t(`adaptive.errors.${run.error.code}`, { defaultValue: run.error.message }) : t('detail.noCandidateFallback')}</small></span></div>}
            {active && <div className="ai-run-active"><Clock3 /><span><strong>{phaseLabel(t, run.phase)}</strong><small>{t('detail.activeHint')}</small></span><b>{run.progress}%</b></div>}
          </DetailPanel>
        </TabsContent>

        <TabsContent value="process" className="run-tab-panel">
          {run.evidence && <AdaptiveEvidence value={run.evidence} />}
          <DetailPanel className="run-detail-section ai-activity-section">
            <header><div><h2>{t('detail.activityHeading')}</h2><p>{t('detail.activitySub')}</p></div>{active && <Badge variant="outline" className="ai-status-badge running"><span />{t('detail.activityStatus.running')}</Badge>}</header>
            {(run.guidance || run.note) && <div className="ai-run-guidance"><MessageSquareText /><span><strong>{t('detail.guidanceHeading')}</strong><small>{t('detail.guidanceSub')}</small><p>{run.guidance ?? run.note}</p></span></div>}
            <AiActivityTimeline activity={run.activity ?? []} />
          </DetailPanel>
          <DetailPanel className="run-detail-section">
            <header><div><h2>{t('detail.attemptsHeading')}</h2><p>{t('detail.attemptsSub')}</p></div></header>
            <div className="ai-attempt-list">
              {run.attempts.map((attempt) => <article key={attempt.id}>
                <span className={`ai-attempt-index ${attempt.status}`}>{['failed', 'timed_out'].includes(attempt.status) ? <TriangleAlert /> : attempt.status === 'running' ? <LoaderCircle className="animate-spin" /> : attempt.status === 'queued' ? <Clock3 /> : <Check />}</span>
                <div><strong>{t('detail.attemptNo', { no: attempt.attemptNo })}</strong><small>{formatDateTime(attempt.startedAt)} · {durationLabel(t, attempt.durationMs)}</small></div>
                <Badge variant="outline">{attemptStatusLabel(t, attempt.status)}</Badge>
                <span className="ai-attempt-models">{t('detail.attemptInvocations', { count: attempt.modelInvocations.length })}</span>
              </article>)}
              {run.attempts.length === 0 && <div className="card-empty">{t('detail.noAttempts')}</div>}
            </div>
          </DetailPanel>
        </TabsContent>

        <TabsContent value="models" className="run-tab-panel">
          <DetailPanel className="run-detail-section ai-model-section">
            <header><div><h2>{t('detail.modelsHeading')}</h2><p>{t('detail.modelsSub')}</p></div></header>
            <div className="ai-model-table">
              <div className="ai-model-head"><span>{t('modelTable.purpose')}</span><span>{t('modelTable.model')}</span><span>{t('modelTable.status')}</span><span>{t('modelTable.token')}</span><span>{t('modelTable.duration')}</span></div>
              {invocations.map((invocation) => <ModelInvocationRow key={invocation.id} invocation={invocation} />)}
              {invocations.length === 0 && <div className="card-empty">{t('modelTable.empty')}</div>}
            </div>
          </DetailPanel>
        </TabsContent>

        <TabsContent value="evidence" className="run-tab-panel">
          {run.evidence && <AdaptiveEvidence value={run.evidence} showReads />}
          <DetailPanel className="run-detail-section run-proof-section" aria-label={t('detail.evidenceAria')}>
            <header><div><h2>{t('detail.evidenceHeading')}</h2><p>{t('detail.evidenceSub')}</p></div><Fingerprint /></header>
            <div className="run-proof-grid">
              <article className="verified"><ListChecks /><span><strong>{t('detail.evidence.attempts', { count: run.attemptCount })}</strong><small>{t('detail.evidence.attemptsSub')}</small></span></article>
              <article className="verified"><Bot /><span><strong>{t('detail.evidence.invocations', { count: run.modelSummary.invocationCount })}</strong><small>{formatTokens(run.modelSummary.totalTokens)} Token</small></span></article>
              <article className={run.resultStatus === 'candidate_ready' ? 'verified' : 'pending'}><FileCheck2 /><span><strong>{run.resultStatus === 'candidate_ready' ? t('detail.evidence.candidateFixed') : t('detail.evidence.noCandidate')}</strong><small>{reviewLabel(t, run.reviewStatus, run.collectorDeleted)}</small></span></article>
              <article className="neutral"><ShieldCheck /><span><strong>{t('detail.evidence.noSensitive')}</strong><small>{t('detail.evidence.noSensitiveSub')}</small></span></article>
            </div>
            <details className="run-technical-details">
              <summary><Braces /><span><strong>{t('detail.technical.heading')}</strong><small>{t('detail.technical.sub')}</small></span><ArrowRight /></summary>
              <dl>
                <div><dt>AI Run ID</dt><dd><code>{run.id}</code></dd></div>
                <div><dt>Operation ID</dt><dd><code>{run.operationId}</code></dd></div>
                <div><dt>Collector ID</dt><dd><code>{run.collectorId}</code></dd></div>
                <div><dt>Candidate Digest</dt><dd><code>{run.candidateRuleDigest ?? 'not available'}</code></dd></div>
                <div><dt>Published Rule</dt><dd><code>{run.publishedRuleVersionId ?? 'not published'}</code></dd></div>
                <div><dt>Initiated By</dt><dd><code>{run.initiatedBy}</code></dd></div>
              </dl>
            </details>
          </DetailPanel>
        </TabsContent>
      </Tabs>
    </div>
  </div>
}

export function AdaptiveEvidence({ value, showReads = false }: { value: NonNullable<AiRunDetail['evidence']>; showReads?: boolean }) {
  const { t } = useTranslation('aiRuns')
  const b = value.budget
  return <DetailPanel className="run-detail-section adaptive-evidence" aria-label={t('adaptive.title')}>
    <header><div><h2>{t('adaptive.title')}</h2><p>{t(`adaptive.source.${value.limitsSource}`)} · {t(`adaptive.method.${b.tokenMethod}`)}</p></div><Badge variant="outline">{t(`adaptive.phase.${value.phase}`)}</Badge></header>
    <dl className="ai-result-grid">
      <div><dt>{t('adaptive.calls')}</dt><dd>{b.calls} / {b.maxCalls}</dd></div>
      <div><dt>{t('adaptive.input')}</dt><dd>{formatTokens(b.inputTokens)} / {formatTokens(b.maxInputTokens)}</dd></div>
      <div><dt>{t('adaptive.output')}</dt><dd>{formatTokens(b.outputTokens)} / {formatTokens(b.maxOutputTokens)}</dd></div>
      <div><dt>{t('adaptive.time')}</dt><dd>{Math.round(b.elapsedSeconds)} / {b.maxSeconds}s</dd></div>
    </dl>
    <div className="adaptive-context"><span>{t('adaptive.context', { count: b.contextTokens })}</span><span>{t(value.validated ? 'adaptive.validated' : 'adaptive.unvalidated')}</span></div>
    {b.stopReason && <div className="ai-run-error"><TriangleAlert /><span><strong>{t('adaptive.stopped')}</strong><small>{t(`adaptive.errors.${b.stopReason}`, { defaultValue: b.stopReason })}</small></span></div>}
    {showReads && <div className="adaptive-table-wrap"><table className="adaptive-table">
      <thead><tr><th>{t('adaptive.page')}</th><th>{t('adaptive.indexed')}</th><th>{t('adaptive.read')}</th><th>{t('adaptive.chars')}</th></tr></thead>
      <tbody>{value.pages.map((page) => <tr key={page.pageId}><td><code>{page.pageId}</code></td><td>{page.indexedNodes}</td><td>{page.readNodes}</td><td>{page.readFragmentChars.toLocaleString()}</td></tr>)}</tbody>
    </table></div>}
    {value.validation.length > 0 && <ul className="adaptive-validation">{value.validation.map((issue, index) => <li key={index}><span title={issue.code}>{t(`adaptive.validation.${issue.code}`, { defaultValue: issue.code ?? '' })}</span>{issue.field && <code>{issue.field}</code>}{issue.sample !== undefined && <span>{t('adaptive.sample', { count: issue.sample })}</span>}</li>)}</ul>}
    {showReads && <details className="adaptive-reads"><summary>{t('adaptive.readLog', { count: value.reads.length })}</summary><div className="adaptive-table-wrap"><table className="adaptive-table">
      <thead><tr><th>{t('adaptive.page')}</th><th>{t('adaptive.node')}</th><th>{t('adaptive.action')}</th><th>{t('adaptive.range')}</th><th>{t('adaptive.fragment')}</th></tr></thead>
      <tbody>{value.reads.map((read, index) => <tr key={index}><td title={read.digest}><code>{read.pageId}</code></td><td><code>{read.nodeId}</code></td><td>{t(`adaptive.actionType.${read.action}`)}</td><td>{read.start}–{read.end}</td><td>{t(read.complete ? 'adaptive.end' : 'adaptive.more')}</td></tr>)}</tbody>
    </table></div></details>}
  </DetailPanel>
}

function AiRunSummary({ run, failed }: { run: AiRunDetail; failed: boolean }) {
  const { t } = useTranslation('aiRuns')
  return <DetailPanel aria-label={t('summaryAria')} className={`run-result-summary ${failed ? 'danger' : run.reviewStatus === 'ready_review' ? 'warning' : 'success'}`}>
    <div className="run-result-heading ai-run-summary">
      <div><h2>{failed ? t('summary.failed') : !run.collectorDeleted && run.reviewStatus === 'ready_review' ? t('summary.readyReview') : resultTitle(t, run)}</h2><p>{t('summary.phaseDuration', { phase: phaseLabel(t, run.phase), duration: durationLabel(t, run.durationMs) })}</p></div>
      <dl className="run-result-facts ai-run-facts">
        <div><dt>{t('summary.facts.invocations')}</dt><dd>{run.modelSummary.invocationCount}</dd></div>
        <div><dt>{t('summary.facts.tokens')}</dt><dd>{formatTokens(run.modelSummary.totalTokens)}</dd></div>
        <div><dt>{t('summary.facts.acceptedSamples')}</dt><dd>{run.validationSummary.acceptedSamples}</dd></div>
        <div><dt>{t('summary.facts.rejectedSamples')}</dt><dd>{run.validationSummary.rejectedSamples}</dd></div>
        <div><dt>{t('summary.facts.warnings')}</dt><dd>{run.validationSummary.warningCount}</dd></div>
        <div><dt>{t('summary.facts.duration')}</dt><dd>{durationLabel(t, run.durationMs)}</dd></div>
      </dl>
    </div>
  </DetailPanel>
}

function ModelInvocationRow({ invocation }: { invocation: ModelInvocation }) {
  const { t } = useTranslation('aiRuns')
  return <div className="ai-model-row">
    <span><strong>{purposeLabel(t, invocation.purpose)}</strong><small>Prompt v{invocation.promptVersion}</small></span>
    <span><strong>{invocation.model}</strong><small>{invocation.provider}</small></span>
    <Badge variant="outline" className={invocation.status === 'succeeded' ? 'ai-model-success' : 'ai-model-failed'}>{invocation.status === 'succeeded' ? t('invocationStatus.succeeded') : t('invocationStatus.failed')}</Badge>
    <span><strong>{formatTokens(invocation.totalTokens)}</strong><small>{t('modelTable.tokens', { prompt: invocation.promptTokens, completion: invocation.completionTokens })}</small></span>
    <span><strong>{durationLabel(t, invocation.durationMs)}</strong><small>{formatDateTime(invocation.startedAt)}</small></span>
  </div>
}

function AiActivityTimeline({ activity }: { activity: OperationActivity[] }) {
  const { t } = useTranslation('aiRuns')
  if (activity.length === 0) return <div className="card-empty">{t('detail.activityEmpty')}</div>
  return <ol className="ai-activity-timeline">
    {activity.map((event, index) => {
      const metric = activityMetric(t, event)
      return <li className={event.status} key={`${event.phase}:${event.startedAt}:${index}`}>
        <span className="ai-activity-marker">{event.status === 'running' ? <LoaderCircle className="animate-spin" /> : event.status === 'failed' ? <TriangleAlert /> : <Check />}</span>
        <span className="ai-activity-copy"><strong>{phaseLabel(t, event.phase)}</strong><small>{formatDateTime(event.startedAt)} · {durationLabel(t, event.durationMs)}</small>{metric && <em>{metric}</em>}</span>
        <Badge variant="outline">{t(`detail.activityStatus.${event.status}`)}</Badge>
      </li>
    })}
  </ol>
}

function AiRunState({ run }: { run: AiRunDetail }) {
  const { t } = useTranslation('aiRuns')
  if (run.collectorDeleted && run.reviewStatus === 'ready_review') return <Badge variant="outline">{t('state.completed')}</Badge>
  const active = ['queued', 'running', 'finalizing'].includes(run.status)
  const label = run.status === 'failed' ? t('state.failed') : active ? t('state.running') : run.reviewStatus === 'ready_review' ? t('state.readyReview') : run.reviewStatus === 'published' ? t('state.published') : t('state.completed')
  return <Badge variant="outline" className={`ai-status-badge ${run.status === 'failed' ? 'danger' : active ? 'running' : run.reviewStatus === 'ready_review' ? 'review' : 'success'}`}><span />{label}</Badge>
}

function sourcePresentation(sourceUrl: string, fallback: string) {
  try {
    const url = new URL(sourceUrl)
    const path = `${url.pathname}${url.search}${url.hash}`
    return { root: url.origin, path: path === '/' ? '' : path, full: url.toString() }
  } catch {
    return { root: fallback, path: sourceUrl, full: sourceUrl }
  }
}

function taskKindLabel(t: TFunction, run: AiRunDetail) {
  return run.kind === 'rule_repair' ? t('taskKind.rule_repair') : run.trigger === 'initial_generation' ? t('taskKind.initial_generation') : t('taskKind.regeneration')
}

function resultTitle(t: TFunction, run: AiRunDetail) {
  if (run.collectorDeleted && run.resultStatus === 'candidate_ready') return t('collectors:management.historicalCandidate')
  if (run.resultStatus === 'candidate_ready') return t('result.candidate_ready')
  if (run.resultStatus === 'no_candidate') return t('result.no_candidate')
  return t('result.pending')
}

function resultDescription(t: TFunction, run: AiRunDetail) {
  if (run.collectorDeleted) return t('collectors:management.deletedNotice')
  if (run.resultStatus === 'no_candidate') return t('adaptive.noCandidate')
  if (run.reviewStatus === 'ready_review') return t('resultDesc.ready_review')
  if (run.reviewStatus === 'published') return t('resultDesc.published')
  if (run.reviewStatus === 'superseded') return t('resultDesc.superseded')
  return t('resultDesc.default')
}

function reviewLabel(t: TFunction, status: AiRunDetail['reviewStatus'], deleted = false) {
  if (deleted && status === 'ready_review') return t('collectors:management.historicalReview')
  return { not_ready: t('reviewStatus.not_ready'), ready_review: t('reviewStatus.ready_review'), published: t('reviewStatus.published'), superseded: t('reviewStatus.superseded') }[status]
}

function phaseLabel(t: TFunction, phase: AiRunDetail['phase']) {
  return { queued: t('phase.queued'), fetching_list: t('phase.fetching_list'), analyzing_structure: t('phase.analyzing_structure'), discovering_details: t('phase.discovering_details'), fetching_details: t('phase.fetching_details'), compiling_rule: t('phase.compiling_rule'), validating: t('phase.validating'), finalizing: t('phase.finalizing'), completed: t('phase.completed') }[phase]
}

function activityMetric(t: TFunction, event: OperationActivity) {
  if (event.phase === 'fetching_list') return t('detail.activityMetric.listPages', { count: event.metrics.listPagesFetched })
  if (event.phase === 'discovering_details') return t('detail.activityMetric.detailUrls', { count: event.metrics.detailUrlsDiscovered })
  if (event.phase === 'fetching_details') return t('detail.activityMetric.detailPages', { count: event.metrics.detailPagesFetched })
  if (event.phase === 'validating' || event.phase === 'finalizing' || event.phase === 'completed') return t('detail.activityMetric.warnings', { count: event.metrics.warningCount })
  return null
}

function attemptStatusLabel(t: TFunction, status: AiRunDetail['attempts'][number]['status']) {
  return { queued: t('attemptStatus.queued'), running: t('attemptStatus.running'), finalizing: t('attemptStatus.finalizing'), succeeded: t('attemptStatus.succeeded'), failed: t('attemptStatus.failed'), cancelled: t('attemptStatus.cancelled'), timed_out: t('attemptStatus.timed_out') }[status]
}

function purposeLabel(t: TFunction, purpose: ModelInvocation['purpose']) {
  return { discover: t('purpose.discover'), compile: t('purpose.compile'), repair: t('purpose.repair') }[purpose]
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(value))
}

function durationLabel(t: TFunction, value: number | null) {
  if (value === null) return t('duration.running')
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`
}

function formatTokens(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}
