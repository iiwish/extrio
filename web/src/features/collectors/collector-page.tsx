import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  Braces,
  CalendarRange,
  CalendarClock,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Download,
  Eye,
  EyeOff,
  FileSearch,
  FileCheck2,
  Globe2,
  Inbox,
  KeyRound,
  Layers3,
  LayoutDashboard,
  ListTree,
  LockKeyhole,
  LoaderCircle,
  MoreHorizontal,
  PanelRightOpen,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Route,
  Rocket,
  Save,
  Send,
  Settings2,
  ShieldCheck,
  Trash2,
  WandSparkles,
  Webhook,
  Wrench,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { ApiRequestError, api, downloadEvidenceBundle, waitForOperation } from '@/api/client'
import type { AiRun, CandidateField, CandidateRule, CandidateRuleEditInput, CollectionPolicy, CollectionPolicyInput, CollectorDetail, CollectorSchedule, CollectorScheduleInput, DeliveryStatus, DeliverySummary, FieldReviewDecision, HarvestItem, Operation, RepairInput, Sink, SinkInput, SinkUpdateInput, UpdateCollectorInput } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { EvidenceRail } from '@/components/evidence-rail'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { collectorDisplayName } from './collector-presentation'

type Translator = TFunction<'collectorDetail', undefined>

export function CollectorPage() {
  const { t } = useTranslation('collectorDetail')
  const { collectorId = '' } = useParams()
  const navigate = useNavigate()
  const { setTopbarBackTarget } = useOutletContext<{ setTopbarBackTarget: (target: string | null) => void }>()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const publishLockReason = user.role === 'reviewer' || user.role === 'administrator' ? null : t('common:roles.publishLocked')
  const query = useQuery({ queryKey: ['collector', collectorId], queryFn: () => api.collector(collectorId) })
  const latestRunQuery = useQuery({
    queryKey: ['run', query.data?.latestRunId],
    queryFn: () => api.runDetail(query.data!.latestRunId!),
    enabled: Boolean(query.data?.latestRunId),
  })
  const aiRunsQuery = useQuery({ queryKey: ['ai-runs', { collectorId }], queryFn: () => api.aiRuns(collectorId) })
  const [selectedField, setSelectedField] = useState<CandidateField | undefined>()
  const [selectedItem, setSelectedItem] = useState<HarvestItem | undefined>()
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const evidenceTriggerRef = useRef<HTMLElement | null>(null)
  const [reviewState, setReviewState] = useState<{ digest: string | null; decisions: Record<string, FieldReviewDecision> }>({ digest: null, decisions: {} })
  const [activeOperation, setActiveOperation] = useState<Operation | undefined>()
  const [operationError, setOperationError] = useState<Error | undefined>()
  const candidate = query.data?.candidate
  const decisionOverrides = reviewState.digest === candidate?.digest ? reviewState.decisions : {}
  const reviewDecisions = Object.fromEntries((candidate?.fields ?? []).map((field) => [field.key, decisionOverrides[field.key] ?? (field.warning ? 'pending' : 'approved')])) as Record<string, FieldReviewDecision>

  useEffect(() => {
    if (!query.data) return
    setTopbarBackTarget(`/collectors?collection=${encodeURIComponent(query.data.collectionId)}`)
    return () => setTopbarBackTarget(null)
  }, [query.data, setTopbarBackTarget])

  const explore = useMutation({
    mutationFn: async () => {
      const accepted = await api.startExploration(collectorId)
      const completed = await waitForOperation(accepted, setActiveOperation)
      return api.collector(completed.resourceId)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['collector', collectorId], data)
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
      queryClient.invalidateQueries({ queryKey: ['ai-runs'] })
    },
  })
  const repair = useMutation({
    mutationFn: async (input: RepairInput) => {
      const accepted = await api.startRepair(collectorId, input)
      const completed = await waitForOperation(accepted, setActiveOperation)
      return api.collector(completed.resourceId)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['collector', collectorId], data)
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
      queryClient.invalidateQueries({ queryKey: ['ai-runs'] })
    },
  })
  const exportEvidence = useMutation({
    mutationFn: () => downloadEvidenceBundle(collectorId),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `extrio-evidence-${collectorId}.zip`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    },
  })
  const publish = useMutation({
    mutationFn: () => api.publish(collectorId, reviewDecisions),
    onSuccess: (data) => {
      setSelectedField(undefined)
      setSelectedItem(undefined)
      setEvidenceOpen(false)
      queryClient.setQueryData(['collector', collectorId], data)
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
      queryClient.invalidateQueries({ queryKey: ['ai-runs'] })
    },
  })
  const savePolicy = useMutation({
    mutationFn: (input: CollectionPolicyInput) => api.saveCollectionPolicy(collectorId, input),
    onSuccess: (data) => {
      queryClient.setQueryData(['collector', collectorId], data)
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
    },
  })
  const saveSchedule = useMutation({
    mutationFn: (input: CollectorScheduleInput) => api.updateCollectorSchedule(collectorId, input),
    onSuccess: (data) => {
      queryClient.setQueryData(['collector', collectorId], data)
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
    },
  })
  const updateDefinition = useMutation({
    mutationFn: (input: UpdateCollectorInput) => api.updateCollector(collectorId, input),
    onSuccess: (data) => {
      setSelectedField(undefined)
      setSelectedItem(undefined)
      setEvidenceOpen(false)
      queryClient.setQueryData(['collector', collectorId], data)
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
    },
  })
  const editCandidate = useMutation({
    mutationFn: (input: CandidateRuleEditInput) => api.updateCandidateRule(collectorId, input),
    onSuccess: (data) => {
      setSelectedField(undefined)
      setSelectedItem(undefined)
      setEvidenceOpen(false)
      setReviewState({ digest: null, decisions: {} })
      queryClient.setQueryData(['collector', collectorId], data)
      queryClient.invalidateQueries({ queryKey: ['collectors'] })
    },
  })
  const run = useMutation({
    mutationFn: async () => {
      const accepted = await api.startRun(collectorId)
      const completed = await waitForOperation(accepted, setActiveOperation)
      return api.runDetail(completed.resourceId)
    },
    onSuccess: () => {
      setSelectedField(undefined)
      setSelectedItem(undefined)
      setEvidenceOpen(false)
      queryClient.invalidateQueries({ queryKey: ['collector', collectorId] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({ queryKey: ['items'] })
    },
  })

  useEffect(() => {
    const operationId = query.data?.activeOperationId
    if (!operationId || explore.isPending || repair.isPending || run.isPending) return
    const controller = new AbortController()
    api.operation(operationId)
      .then((operation) => waitForOperation(operation, setActiveOperation, controller.signal))
      .then(async (operation) => {
        if (operation.kind === 'explore') {
          const data = await api.collector(operation.resourceId)
          queryClient.setQueryData(['collector', collectorId], data)
          queryClient.invalidateQueries({ queryKey: ['collectors'] })
          return
        }
        await api.runDetail(operation.resourceId)
        setSelectedField(undefined)
        setSelectedItem(undefined)
        setEvidenceOpen(false)
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['collector', collectorId] }),
          queryClient.invalidateQueries({ queryKey: ['collectors'] }),
          queryClient.invalidateQueries({ queryKey: ['runs'] }),
          queryClient.invalidateQueries({ queryKey: ['items'] }),
        ])
      })
      .catch((error: Error) => {
        if (error.name !== 'AbortError') setOperationError(error)
      })
    return () => controller.abort()
  }, [collectorId, explore.isPending, query.data?.activeOperationId, queryClient, repair.isPending, run.isPending])

  if (query.isLoading) return <CollectorSkeleton />
  const collector = query.data
  if (!collector) return <NotFound message={query.error?.message ?? t('notFound.missingCollector')} />

  async function startExploration() {
    setActiveOperation(undefined)
    setOperationError(undefined)
    await explore.mutateAsync()
  }

  async function startRepair(input: RepairInput) {
    setActiveOperation(undefined)
    setOperationError(undefined)
    await repair.mutateAsync(input)
  }

  function startRun() {
    setActiveOperation(undefined)
    setOperationError(undefined)
    run.mutate()
  }

  const latestRun = run.data ?? latestRunQuery.data
  const latestAiRun = aiRunsQuery.data?.find((aiRun) => aiRun.collectorId === collector.id)
  const persistedRunPending = collector.status === 'published' && Boolean(collector.activeOperationId)
  const runPending = run.isPending || persistedRunPending
  const hasPendingDecision = candidate?.fields.some((field) => (reviewDecisions[field.key] ?? 'pending') === 'pending') ?? true
  const pendingDecisionCount = candidate?.fields.filter((field) => (reviewDecisions[field.key] ?? 'pending') === 'pending').length ?? 0
  const repairable = Boolean(collector.candidate?.gatherSpec || collector.activeRuleVersion)
  const repairErrorMessage = repair.error instanceof ApiRequestError && repair.error.code === 'REPAIR_NOT_APPLICABLE'
    ? t('repair.notApplicable')
    : repair.error?.message
  const evidenceErrorMessage = exportEvidence.error instanceof ApiRequestError && exportEvidence.error.code === 'EVIDENCE_BUNDLE_ERROR'
    ? t('evidence.bundleError')
    : exportEvidence.error?.message

  function openFieldEvidence(field: CandidateField) {
    evidenceTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setSelectedField(field)
    setSelectedItem(undefined)
    setEvidenceOpen(true)
  }

  function openItemEvidence(item: HarvestItem) {
    evidenceTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setSelectedItem(item)
    setSelectedField(undefined)
    setEvidenceOpen(true)
  }

  function handleEvidenceOpenChange(next: boolean) {
    setEvidenceOpen(next)
    if (!next) requestAnimationFrame(() => evidenceTriggerRef.current?.focus())
  }

  return (
    <div className="collector-workbench">
      <div className="workbench-main">
        <header className="object-header">
          <div className="object-title">
            <span className="source-icon large"><Globe2 /></span>
            <div><div className="title-line"><h1>{collectorDisplayName(collector.name)}</h1><StatusBadge status={collector.status} /></div><p className="object-subtitle"><Link className="collection-context-link" to={`/collectors?collection=${encodeURIComponent(collector.collectionId)}`}><Layers3 />{collector.collectionName}</Link><span className="collector-phase">{t('header.currentPhase')}<strong>{t(collectorPhaseLabel(collector.status, explore.isPending || repair.isPending, runPending))}</strong></span></p></div>
          </div>
          <div className="object-actions">
            {collector.status === 'draft' && <Button size="lg" onClick={() => { void startExploration().catch(() => undefined) }} disabled={explore.isPending}>{explore.isPending ? <><LoaderCircle className="animate-spin" />{t('header.exploringNow')}</> : <><Rocket />{t('header.generateCandidates')}</>}</Button>}
            {collector.status === 'exploring' && <Button size="lg" disabled><LoaderCircle className="animate-spin" />{t('header.exploringInProgress')}</Button>}
            {collector.status === 'ready_review' && candidate && (
              <PublishDialog
                candidate={candidate}
                decisions={reviewDecisions}
                pending={publish.isPending}
                disabled={hasPendingDecision}
                lockReason={publishLockReason}
                onPublish={() => publish.mutate()}
              />
            )}
            {collector.status === 'published' && <Button size="lg" onClick={startRun} disabled={runPending || explore.isPending}>{runPending ? <><LoaderCircle className="animate-spin" />{t('header.runningNow')}</> : <><Play />{t('header.runNow')}</>}</Button>}
            {repairable && <RepairRuleDialog disabled={explore.isPending || repair.isPending || runPending || Boolean(collector.activeOperationId)} pending={repair.isPending} onRepair={(input) => startRepair(input)} />}
            <EvidenceExportButton pending={exportEvidence.isPending} onExport={() => exportEvidence.mutate()} />
          </div>
        </header>

        {(explore.isPending || repair.isPending || collector.status === 'exploring') && <ExplorationProgress operation={activeOperation} singleStage={isSingleStageSource(collector.sourceUrl)} />}
        {runPending && <RunProgress operation={activeOperation} />}
        {(explore.error || repair.error || exportEvidence.error || publish.error || savePolicy.error || saveSchedule.error || updateDefinition.error || editCandidate.error || run.error || operationError) && <Alert variant="destructive" className="mt-5"><AlertTitle>{t('header.operationIncomplete')}</AlertTitle><AlertDescription>{repairErrorMessage ?? evidenceErrorMessage ?? explore.error?.message ?? publish.error?.message ?? savePolicy.error?.message ?? saveSchedule.error?.message ?? updateDefinition.error?.message ?? editCandidate.error?.message ?? run.error?.message ?? operationError?.message}</AlertDescription></Alert>}

        <Tabs key={`${collector.id}:${collector.status}`} defaultValue={defaultCollectorTab(collector.status)} className="collector-workspace-tabs">
          <div className="collector-workspace-nav">
            <TabsList variant="line" aria-label={t('header.viewsAria')}>
              <TabsTrigger value="overview"><LayoutDashboard />{t('common:nav.overview')}</TabsTrigger>
              {candidate && <TabsTrigger value="rule"><ClipboardCheck />{collector.status === 'ready_review' ? t('header.ruleReviewTab') : t('header.ruleTab')}{pendingDecisionCount > 0 && <span className="tab-count">{pendingDecisionCount}</span>}</TabsTrigger>}
              <TabsTrigger value="config"><Settings2 />{t('header.configTab')}</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="overview" className="collector-workspace-panel">
            <CollectorOverview
              collector={collector}
              latestRun={latestRun}
              latestAiRun={latestAiRun}
              runPending={runPending}
              onSelectItem={openItemEvidence}
              onOpenRun={(id) => navigate(`/runs/${id}`)}
            />
          </TabsContent>

          <TabsContent value="config" className="collector-workspace-panel configuration-workspace">
            <CollectorConfiguration
              key={`${collector.id}:${collector.collectionId}:${collector.sourceUrl}:${collector.intent}:${candidate?.digest ?? 'none'}`}
              collector={collector}
              disabled={Boolean(collector.activeOperationId) || runPending}
              definitionPending={updateDefinition.isPending}
              rulePending={editCandidate.isPending || explore.isPending}
              onSaveDefinition={(input) => updateDefinition.mutateAsync(input)}
              onSaveRule={(input) => editCandidate.mutateAsync(input)}
              onRegenerate={startExploration}
            />
            <SchedulePanel
              key={`${collector.schedule.id}:${collector.schedule.revision}`}
              schedule={collector.schedule}
              disabled={Boolean(collector.activeOperationId) || saveSchedule.isPending}
              pending={saveSchedule.isPending}
              onSave={(input) => saveSchedule.mutate(input)}
            />
            <CollectionPolicyPanel
              key={collector.collectionPolicy?.digest ?? collector.id}
              policy={collector.collectionPolicy}
              disabled={Boolean(collector.activeOperationId) || savePolicy.isPending}
              pending={savePolicy.isPending}
              onSave={(input) => savePolicy.mutate(input)}
            />
            <WebhookPushPanel collectorId={collector.id} />
            <DeliveryLogPanel collectorId={collector.id} />
          </TabsContent>

          <TabsContent value="rule" className="collector-workspace-panel">
            {candidate && (collector.status === 'ready_review' ? <ReviewWorkspace
              candidate={candidate}
              previewItems={collector.previewItems}
              selectedField={selectedField}
              decisions={reviewDecisions}
              onSelectField={openFieldEvidence}
              onSelectItem={openItemEvidence}
              onDecision={(key, decision) => setReviewState((current) => ({
                digest: candidate.digest,
                decisions: { ...(current.digest === candidate.digest ? current.decisions : {}), [key]: decision },
              }))}
            /> : <ValidationWorkspace candidate={candidate} sourceUrl={collector.sourceUrl} published={collector.status === 'published'} reviewDecisions={collector.reviewDecisions ?? reviewDecisions} />)}
          </TabsContent>
        </Tabs>
      </div>
      <Sheet open={evidenceOpen} onOpenChange={handleEvidenceOpenChange}>
        <SheetContent className="collector-evidence-sheet">
          <SheetHeader className="sr-only">
            <SheetTitle>{t('evidenceSheet.title')}</SheetTitle>
            <SheetDescription>{t('evidenceSheet.description')}</SheetDescription>
          </SheetHeader>
          <ScrollArea className="collector-evidence-scroll">
            <EvidenceRail
              mode="drawer"
              collector={collector}
              field={selectedField}
              fieldDecision={selectedField ? reviewDecisions[selectedField.key] ?? 'pending' : undefined}
              item={selectedItem}
            />
          </ScrollArea>
        </SheetContent>
      </Sheet>
    </div>
  )
}

export function defaultCollectorTab(status: CollectorDetail['status']) {
  if (status === 'ready_review') return 'rule'
  return 'overview'
}

function collectorPhaseLabel(status: CollectorDetail['status'], exploring: boolean, running: boolean) {
  if (exploring || status === 'exploring') return 'common:stage.explore'
  if (running) return 'common:stage.run'
  if (status === 'ready_review') return 'common:stage.review'
  if (status === 'published') return 'common:status.published'
  return 'common:stage.design'
}

function WorkspaceEmpty({ icon: Icon, title, description }: { icon: typeof ClipboardCheck; title: string; description: string }) {
  return <section className="collector-workspace-empty"><span><Icon /></span><div><h2>{title}</h2><p>{description}</p></div></section>
}

function CollectorOverview({ collector, latestRun, latestAiRun, runPending, onSelectItem, onOpenRun }: {
  collector: CollectorDetail
  latestRun: Awaited<ReturnType<typeof api.runDetail>> | undefined
  latestAiRun: AiRun | undefined
  runPending: boolean
  onSelectItem: (item: HarvestItem) => void
  onOpenRun: (id: string) => void
}) {
  const { t } = useTranslation('collectorDetail')
  const candidate = collector.candidate
  const items = latestRun?.items ?? collector.previewItems
  const runId = latestRun?.id ?? collector.latestRunId
  const acceptedCount = items.filter((item) => item.decision === 'accepted').length
  const rejectedCount = items.filter((item) => item.decision === 'rejected').length
  const pagination = candidate?.pagination.type === 'page'
    ? t('overview.pagination.maxPages', { maxPages: candidate.pagination.maxPages })
    : candidate?.pagination.type === 'next_link'
      ? t('overview.pagination.nextLink', { maxPages: candidate.pagination.maxPages })
      : candidate?.mode === 'single' ? t('overview.pagination.single') : t('overview.pagination.listOnePage')

  return <div className="collector-overview">
    <section className="collector-overview-summary">
      <div className="overview-state">
        <span className={`overview-state-icon ${collector.status === 'published' ? 'success' : ''}`}>{collector.status === 'published' ? <ShieldCheck /> : <Route />}</span>
        <div><span className="eyebrow">CURRENT STATE</span><h2>{runPending ? t('overview.runningTitle') : t(overviewTitle(collector.status))}</h2><p>{t(overviewDescription(collector.status, runPending))}</p></div>
        {latestAiRun && <Link className="overview-ai-run" to={`/ai-runs/${latestAiRun.id}`}><WandSparkles /><span><strong>{t('overview.aiRun.title')}</strong><small>{t(aiRunReviewLabel(latestAiRun))} · {t('overview.aiRun.invocations', { total: latestAiRun.modelSummary.invocationCount })}</small></span><ChevronRight /></Link>}
      </div>
      <dl className="overview-facts">
        <div><dt>{t('overview.facts.sourceUrl')}</dt><dd><code className="overview-source-url" title={collector.sourceUrl}>{collector.sourceUrl}</code></dd></div>
        <div><dt>{t('overview.facts.activeRule')}</dt><dd><strong>{collector.activeRuleVersion ? t('overview.facts.fieldsSummary', { total: candidate?.fields.length ?? 0, mode: candidate?.mode === 'single' ? t('overview.mode.single') : t('overview.mode.listDetail') }) : t('overview.facts.notPublished')}</strong><span>{collector.activeRuleVersion ? t('overview.facts.publishedFrozen') : t('overview.facts.awaitingReview')}</span></dd></div>
        <div><dt>{t('overview.facts.runScope')}</dt><dd><strong>{pagination}</strong><span>{collector.collectionPolicy ? t('overview.facts.lookbackSummary', { days: collector.collectionPolicy.lookbackDays, maxItems: collector.collectionPolicy.maxItems }) : t('overview.facts.defaultPolicy')}</span></dd></div>
        <div><dt>{t('overview.facts.latestRun')}</dt><dd><strong>{runId ? t('overview.facts.runDecisions', { accepted: acceptedCount, rejected: rejectedCount }) : t('overview.facts.noRuns')}</strong><span>{runId ? t('overview.facts.runMeta', { duration: latestRun?.duration ?? t('overview.facts.completedDuration'), watermark: collector.checkpoint?.watermark ?? t('overview.facts.noWatermark') }) : t('overview.facts.publishToRun')}</span></dd></div>
      </dl>
    </section>
    {runPending ? <WorkspaceEmpty icon={Play} title={t('overview.empty.title')} description={t('overview.empty.description')} /> : collector.status === 'published' ? <PublishedView items={items} runId={runId} onSelectItem={onSelectItem} onOpenRun={onOpenRun} /> : <section className="overview-guidance"><div><span className="eyebrow">NEXT STEP</span><h2>{collector.status === 'ready_review' ? t('overview.nextStep.readyReviewTitle') : t('overview.nextStep.designTitle')}</h2><p>{collector.status === 'ready_review' ? t('overview.nextStep.readyReviewDescription') : t('overview.nextStep.designDescription')}</p></div></section>}
  </div>
}

function aiRunReviewLabel(run: AiRun) {
  if (['queued', 'running', 'finalizing'].includes(run.status)) return 'overview.aiRun.inProgress'
  if (run.status === 'failed') return 'common:status.failed'
  return { not_ready: 'overview.aiRun.notReady', ready_review: 'common:status.ready_review', published: 'common:status.published', superseded: 'overview.aiRun.superseded' }[run.reviewStatus]
}

function overviewTitle(status: CollectorDetail['status']) {
  if (status === 'published') return 'overview.state.published'
  if (status === 'ready_review') return 'overview.state.readyReview'
  if (status === 'exploring') return 'overview.state.exploring'
  return 'overview.state.draft'
}

function overviewDescription(status: CollectorDetail['status'], running: boolean) {
  if (running) return 'overview.description.running'
  if (status === 'published') return 'overview.description.published'
  if (status === 'ready_review') return 'overview.description.readyReview'
  if (status === 'exploring') return 'overview.description.exploring'
  return 'overview.description.draft'
}

function ValidationWorkspace({ candidate, sourceUrl, published, reviewDecisions }: {
  candidate: CandidateRule
  sourceUrl: string
  published: boolean
  reviewDecisions: Record<string, FieldReviewDecision>
}) {
  const { t } = useTranslation('collectorDetail')
  const acceptedRisk = Object.values(reviewDecisions).filter((decision) => decision === 'risk_accepted').length
  const excluded = Object.values(reviewDecisions).filter((decision) => decision === 'excluded').length
  const decisionSummary = excluded > 0
    ? t('validation.decisionSummary.excluded', { total: excluded })
    : acceptedRisk > 0
      ? t('validation.decisionSummary.riskAccepted', { total: acceptedRisk })
      : t('validation.decisionSummary.allPassed')

  return <div className="validation-workspace">
    <section className="validation-summary">
      <div className="validation-summary-heading"><div><span className="eyebrow">RULE RELEASE</span><h2>{published ? t('validation.title.published') : t('validation.title.candidate')}</h2><p>{published ? t('validation.description.published') : t('validation.description.candidate')}</p></div><Badge variant="outline">{published ? t('common:status.published') : t('validation.badgeCandidate')}</Badge></div>
      <div className="validation-metrics">
        <span><strong>{candidate.passedChecks}</strong><small>{t('validation.metrics.passed')}</small></span>
        <span><strong>{candidate.warningChecks}</strong><small>{t('common:evidence.qualityWarning')}</small></span>
        <span><strong>{candidate.discovery.detailPagesValidated}</strong><small>{t('validation.metrics.detailSamples')}</small></span>
        <span><strong>{candidate.fields.length}</strong><small>{t('validation.metrics.outputFields')}</small></span>
      </div>
      <div className="validation-release-facts">
        <span><small>{t('validation.flowLabel')}</small><strong>{candidate.mode === 'single' ? t('overview.pagination.single') : t('validation.flowListDetail')}</strong></span>
        <span><small>{t('validation.decisionLabel')}</small><strong>{decisionSummary}</strong></span>
      </div>
    </section>

    <CollectionFlow candidate={candidate} sourceUrl={sourceUrl} />
  </div>
}

function CollectorConfiguration({
  collector,
  disabled,
  definitionPending,
  rulePending,
  onSaveDefinition,
  onSaveRule,
  onRegenerate,
}: {
  collector: CollectorDetail
  disabled: boolean
  definitionPending: boolean
  rulePending: boolean
  onSaveDefinition: (input: UpdateCollectorInput) => Promise<CollectorDetail>
  onSaveRule: (input: CandidateRuleEditInput) => Promise<CollectorDetail>
  onRegenerate: () => Promise<void>
}) {
  const { t } = useTranslation('collectorDetail')
  const candidate = collector.candidate
  const ruleState = !candidate
    ? t('config.ruleState.none')
    : collector.status === 'published'
      ? t('config.ruleState.active')
      : t('config.ruleState.candidate')
  const pagination = candidate?.pagination.type === 'next_link'
    ? t('config.pagination.nextLink', { maxPages: candidate.pagination.maxPages })
    : candidate?.pagination.type === 'page'
      ? t('config.pagination.pageParam', { parameter: candidate.pagination.parameter, maxPages: candidate.pagination.maxPages })
      : t('config.pagination.none')

  return (
    <section className="collector-configuration-grid" aria-label={t('config.gridAria')}>
      <article className="configuration-card definition-card">
        <div className="configuration-heading">
          <span className="configuration-icon teal"><Settings2 /></span>
          <div><span className="eyebrow">COLLECTOR DEFINITION</span><h2>{t('config.definition.title')}</h2></div>
          <DefinitionDialog
            collector={collector}
            disabled={disabled}
            pending={definitionPending}
            onSave={onSaveDefinition}
            onRegenerate={onRegenerate}
          />
        </div>
        <dl className="configuration-facts">
          <div><dt>{t('config.definition.requirement')}</dt><dd><Link className="configuration-collection-link" to={`/collectors?collection=${encodeURIComponent(collector.collectionId)}`}><Layers3 />{collector.collectionName}</Link></dd></div>
          <div><dt>{t('config.definition.intent')}</dt><dd>{collector.intent}</dd></div>
          <div><dt>{t('overview.facts.sourceUrl')}</dt><dd><code>{collector.sourceUrl}</code></dd></div>
        </dl>
        <div className="configuration-footer"><span><LockKeyhole />{t('config.definition.dataContract')}</span><code>{collector.collectionVersion}</code></div>
      </article>

      <article className="configuration-card rule-workspace-card">
        <div className="configuration-heading">
          <span className="configuration-icon blue"><Braces /></span>
          <div><span className="eyebrow">RULE WORKSPACE</span><h2>{t('config.rule.workspaceTitle')}</h2></div>
          <Badge variant={collector.status === 'published' ? 'default' : 'outline'}>{ruleState}</Badge>
        </div>
        {candidate ? <>
          <div className="rule-version-row"><span><small>{t('config.rule.statusLabel')}</small><strong>{collector.status === 'published' ? t('overview.facts.publishedFrozen') : t('config.rule.awaitingReview')}</strong></span><span><small>{t('config.rule.modeLabel')}</small><strong>{candidate.mode === 'single' ? t('config.rule.modeSingle') : t('config.rule.modeListDetail')}</strong></span><span><small>{t('config.rule.fieldsLabel')}</small><strong>{t('config.rule.fieldsCount', { total: candidate.fields.length })}</strong></span></div>
          <dl className="rule-facts"><div><dt>{t('config.rule.listSelector')}</dt><dd><code>{candidate.listSelector}</code></dd></div><div><dt>{t('config.rule.pagination')}</dt><dd>{pagination}</dd></div></dl>
        </> : <div className="rule-empty"><WandSparkles /><div><strong>{t('config.rule.emptyTitle')}</strong><p>{t('config.rule.emptyDescription')}</p></div></div>}
        {collector.status === 'draft' && collector.activeRuleVersion && <p className="rule-rebuild-warning">{t('config.rule.rebuildWarning')}</p>}
        <div className="configuration-actions">
          <RegenerateRuleDialog disabled={disabled || rulePending} pending={rulePending} hasCandidate={Boolean(candidate)} onRegenerate={onRegenerate} />
          {candidate && <RuleEditorDialog candidate={candidate} disabled={disabled || rulePending} pending={rulePending} onSave={onSaveRule} />}
        </div>
      </article>
    </section>
  )
}

function DefinitionDialog({ collector, disabled, pending, onSave, onRegenerate }: {
  collector: CollectorDetail
  disabled: boolean
  pending: boolean
  onSave: (input: UpdateCollectorInput) => Promise<CollectorDetail>
  onRegenerate: () => Promise<void>
}) {
  const { t } = useTranslation('collectorDetail')
  const displayName = collectorDisplayName(collector.name)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<UpdateCollectorInput>({ name: displayName, intent: collector.intent, sourceUrl: collector.sourceUrl })
  const [action, setAction] = useState<'save' | 'regenerate' | null>(null)
  const changed = draft.name.trim() !== displayName || draft.intent.trim() !== collector.intent || draft.sourceUrl.trim() !== collector.sourceUrl
  const ruleInputChanged = draft.intent.trim() !== collector.intent || draft.sourceUrl.trim() !== collector.sourceUrl
  const valid = Boolean(draft.name.trim() && draft.intent.trim() && draft.sourceUrl.trim())

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) setDraft({ name: displayName, intent: collector.intent, sourceUrl: collector.sourceUrl })
    setOpen(nextOpen)
  }

  async function submit(regenerate: boolean) {
    setAction(regenerate ? 'regenerate' : 'save')
    try {
      await onSave({ name: draft.name.trim(), intent: draft.intent.trim(), sourceUrl: draft.sourceUrl.trim() })
      if (regenerate) await onRegenerate()
      setOpen(false)
    } catch {
      return
    } finally {
      setAction(null)
    }
  }

  return <Dialog open={open} onOpenChange={handleOpenChange}><DialogTrigger asChild><Button variant="ghost" size="sm" disabled={disabled}><Pencil />{t('config.definition.edit')}</Button></DialogTrigger><DialogContent className="definition-dialog"><DialogHeader><DialogTitle>{t('config.definition.dialogTitle')}</DialogTitle><DialogDescription>{t('config.definition.dialogDescription')}</DialogDescription></DialogHeader><div className="definition-form"><label><span>{t('config.definition.name')}</span><Input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label><label><span>{t('config.definition.intent')}</span><Textarea rows={5} value={draft.intent} onChange={(event) => setDraft((current) => ({ ...current, intent: event.target.value }))} /></label><label><span>{t('overview.facts.sourceUrl')}</span><Input className="selector-input" value={draft.sourceUrl} onChange={(event) => setDraft((current) => ({ ...current, sourceUrl: event.target.value }))} /></label></div>{ruleInputChanged && <Alert><RefreshCw /><AlertTitle>{t('config.definition.newRuleTitle')}</AlertTitle><AlertDescription>{t('config.definition.newRuleDescription')}</AlertDescription></Alert>}<DialogFooter><Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>{t('common:action.cancel')}</Button><Button variant="outline" onClick={() => void submit(false)} disabled={!changed || !valid || pending}>{action === 'save' ? <LoaderCircle className="animate-spin" /> : <Save />}{ruleInputChanged ? t('config.definition.saveOnly') : t('config.definition.save')}</Button>{ruleInputChanged && <Button onClick={() => void submit(true)} disabled={!changed || !valid || pending}>{action === 'regenerate' ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}{action === 'regenerate' ? t('config.action.generating') : t('config.definition.saveAndRegenerate')}</Button>}</DialogFooter></DialogContent></Dialog>
}

function RegenerateRuleDialog({ disabled, pending, hasCandidate, onRegenerate }: { disabled: boolean; pending: boolean; hasCandidate: boolean; onRegenerate: () => Promise<void> }) {
  const { t } = useTranslation('collectorDetail')
  const [open, setOpen] = useState(false)
  async function submit() {
    try {
      await onRegenerate()
      setOpen(false)
    } catch {
      return
    }
  }
  if (!hasCandidate) return <Button onClick={() => void submit()} disabled={disabled}>{pending ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}{pending ? t('config.action.generating') : t('header.generateCandidates')}</Button>
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button variant="outline" disabled={disabled}><RefreshCw />{t('config.action.regenerate')}</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>{t('config.regenerate.dialogTitle')}</DialogTitle><DialogDescription>{t('config.regenerate.dialogDescription')}</DialogDescription></DialogHeader><DialogFooter><Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>{t('common:action.cancel')}</Button><Button onClick={() => void submit()} disabled={pending}>{pending ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}{pending ? t('config.action.generating') : t('config.regenerate.confirm')}</Button></DialogFooter></DialogContent></Dialog>
}

function RepairRuleDialog({ disabled, pending, onRepair }: { disabled: boolean; pending: boolean; onRepair: (input: RepairInput) => Promise<void> }) {
  const { t } = useTranslation('collectorDetail')
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  async function submit() {
    try {
      await onRepair({ note: note.trim() || undefined })
      setOpen(false)
    } catch {
      setOpen(false)
      return
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="outline" size="lg" disabled={disabled} aria-label={t('repair.actionAria')}><Wrench />{t('repair.action')}</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('repair.dialogTitle')}</DialogTitle>
          <DialogDescription>{t('repair.dialogDescription')}</DialogDescription>
        </DialogHeader>
        <label className="definition-form">
          <span>{t('repair.noteLabel')}</span>
          <Textarea rows={3} maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} placeholder={t('repair.notePlaceholder')} />
        </label>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>{t('common:action.cancel')}</Button>
          <Button onClick={() => void submit()} disabled={pending}>{pending ? <LoaderCircle className="animate-spin" /> : <Wrench />}{pending ? t('repair.repairing') : t('repair.confirm')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EvidenceExportButton({ pending, onExport }: { pending: boolean; onExport: () => void }) {
  const { t } = useTranslation('collectorDetail')
  return (
    <Button variant="outline" size="lg" disabled={pending} aria-label={t('evidence.exportAria')} onClick={onExport}>
      {pending ? <LoaderCircle className="animate-spin" /> : <Download />}{pending ? t('evidence.exporting') : t('evidence.export')}
    </Button>
  )
}

type GatherFieldRule = CandidateRule['gatherSpec']['collect']['list']['fields'][string]

type RuleFieldDraft = {
  key: string
  label: string
  selector: string
}

type RuleEditorDraft = {
  listSelector: string
  paginationType: 'none' | 'next_link' | 'page'
  paginationSelector: string
  pageParameter: string
  pageStart: number
  pageStep: number
  maxPages: number
  stopWhenNoItems: boolean
  listFields: RuleFieldDraft[]
  detailFields: RuleFieldDraft[]
}

function listFieldLabels(t: Translator): Record<string, string> {
  return {
    title: t('config.fieldLabels.title'),
    publishTime: t('config.fieldLabels.publishTime'),
    listTitle: t('config.fieldLabels.listTitle'),
    listPublishedAt: t('config.fieldLabels.listPublishedAt'),
    detailUrl: t('config.fieldLabels.detailUrl'),
  }
}

const systemManagedFieldKeys = new Set(['source', 'crawlTime', 'observedAt'])

function fieldDrafts(rules: Record<string, GatherFieldRule>, labels: Record<string, string>): RuleFieldDraft[] {
  return Object.entries(rules).map(([key, rule]) => ({
    key,
    label: labels[key] ?? key,
    selector: rule.selector,
  }))
}

function ruleEditorDraft(candidate: CandidateRule, t: Translator): RuleEditorDraft {
  const outputFields = candidate.mode === 'list_detail' && candidate.gatherSpec.collect.detail
    ? candidate.gatherSpec.collect.detail.fields
    : candidate.gatherSpec.collect.list.fields
  const outputLabels = Object.fromEntries(candidate.fields.map((field) => [field.key, field.label]))
  const pagination = candidate.pagination
  return {
    listSelector: candidate.listSelector,
    paginationType: pagination.type,
    paginationSelector: pagination.type === 'next_link' ? pagination.selector : '',
    pageParameter: pagination.type === 'page' ? pagination.parameter : 'page',
    pageStart: pagination.type === 'page' ? pagination.start : 1,
    pageStep: pagination.type === 'page' ? pagination.step : 1,
    maxPages: 'maxPages' in pagination ? pagination.maxPages : 1,
    stopWhenNoItems: pagination.type === 'page' ? pagination.stopWhenNoItems : true,
    listFields: candidate.mode === 'list_detail'
      ? fieldDrafts(candidate.gatherSpec.collect.list.fields, listFieldLabels(t))
      : [],
    detailFields: fieldDrafts(outputFields, outputLabels),
  }
}

function ruleEditInput(draft: RuleEditorDraft, mode: CandidateRule['mode']): CandidateRuleEditInput {
  const pagination: CandidateRuleEditInput['pagination'] = mode === 'single' || draft.paginationType === 'none'
    ? { type: 'none' }
    : draft.paginationType === 'page'
      ? { type: 'page', parameter: draft.pageParameter.trim(), start: draft.pageStart, step: draft.pageStep, maxPages: draft.maxPages, stopWhenNoItems: draft.stopWhenNoItems }
      : { type: 'next_link', selector: draft.paginationSelector.trim(), maxPages: draft.maxPages, allowCrossHost: false }
  const detailLinkSelector = draft.listFields.find((field) => field.key === 'detailUrl')?.selector.trim() ?? null
  return {
    listSelector: draft.listSelector.trim(),
    detailLinkSelector: mode === 'single' ? null : detailLinkSelector,
    pagination,
    listFields: mode === 'list_detail'
      ? draft.listFields.map(({ key, selector }) => ({ key, selector: selector.trim() }))
      : undefined,
    fields: draft.detailFields.map(({ key, selector }) => ({ key, selector: selector.trim() })),
  }
}

function RuleFieldEditor({ field, onChange }: { field: RuleFieldDraft; onChange: (selector: string) => void }) {
  return <div className="rule-field-editor-row">
    <div className="rule-field-identity"><strong>{field.label}</strong>{field.label !== field.key && <code>{field.key}</code>}</div>
    <div className="rule-field-control"><Input aria-label={`${field.label} selector`} className="selector-input" value={field.selector} onChange={(event) => onChange(event.target.value)} /></div>
  </div>
}

function RuleEditorDialog({ candidate, disabled, pending, onSave }: { candidate: CandidateRule; disabled: boolean; pending: boolean; onSave: (input: CandidateRuleEditInput) => Promise<CollectorDetail> }) {
  const { t } = useTranslation('collectorDetail')
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<RuleEditorDraft>(() => ruleEditorDraft(candidate, t))
  const input = ruleEditInput(draft, candidate.mode)
  const original = ruleEditInput(ruleEditorDraft(candidate, t), candidate.mode)
  const changed = JSON.stringify(input) !== JSON.stringify(original)
  const allSelectors = [...(input.listFields ?? []), ...input.fields]
  const paginationValid = input.pagination.type === 'none'
    || ('maxPages' in input.pagination && input.pagination.maxPages > 0 && (input.pagination.type !== 'next_link' || input.pagination.selector.length >= 5))
  const valid = input.listSelector.length >= 5
    && allSelectors.every((field) => field.selector.length >= 5)
    && paginationValid
    && (candidate.mode === 'single' || Boolean(input.detailLinkSelector))
  const changeCount = [
    input.listSelector !== original.listSelector,
    JSON.stringify(input.pagination) !== JSON.stringify(original.pagination),
    ...(input.listFields ?? []).map((field, index) => field.selector !== original.listFields?.[index]?.selector),
    ...input.fields.map((field, index) => field.selector !== original.fields[index]?.selector),
  ].filter(Boolean).length
  function setField(group: 'listFields' | 'detailFields', index: number, selector: string) {
    setDraft((current) => ({
      ...current,
      [group]: current[group].map((field, fieldIndex) => fieldIndex === index ? { ...field, selector } : field),
    }))
  }

  function setDialogOpen(next: boolean) {
    if (next) setDraft(ruleEditorDraft(candidate, t))
    setOpen(next)
  }

  async function submit() {
    try {
      await onSave(input)
      setOpen(false)
    } catch {
      return
    }
  }

  return <Dialog open={open} onOpenChange={setDialogOpen}>
    <DialogTrigger asChild><Button disabled={disabled}><Pencil />{t('config.editor.editRule')}</Button></DialogTrigger>
    <DialogContent className="rule-editor-dialog">
      <DialogHeader className="rule-editor-header">
        <div><DialogTitle>{t('config.editor.editRule')}</DialogTitle><DialogDescription>{t('config.editor.dialogDescription')}</DialogDescription></div>
      </DialogHeader>
      <Tabs defaultValue="edit" className="rule-editor-tabs">
        <div className="rule-editor-tabbar"><TabsList variant="line" aria-label={t('config.editor.viewsAria')}><TabsTrigger value="edit"><Pencil />{t('config.editor.editTab')}</TabsTrigger><TabsTrigger value="contract"><Braces />JSON</TabsTrigger></TabsList></div>
        <TabsContent value="edit" className="rule-editor-edit-panel">
      <div className="rule-editor-scroll">
          <section className="rule-stage-section">
            <div className="rule-stage-marker"><span>1</span></div>
            <div className="rule-stage-content">
              <header><h3>{candidate.mode === 'single' ? t('config.editor.stageSingleTitle') : t('config.editor.stageListTitle')}</h3></header>
              <label className="rule-primary-selector"><span>Item selector</span><Input aria-label={t('config.editor.listSelectorAria')} className="selector-input" value={draft.listSelector} onChange={(event) => setDraft((current) => ({ ...current, listSelector: event.target.value }))} /></label>
              {candidate.mode === 'list_detail' && <div className="rule-subsection"><div className="rule-subsection-heading"><h4>{t('config.editor.listFields')}</h4></div><div className="rule-field-editor-list">{draft.listFields.map((field, index) => systemManagedFieldKeys.has(field.key) ? null : <RuleFieldEditor key={field.key} field={field} onChange={(selector) => setField('listFields', index, selector)} />)}</div></div>}
              {candidate.mode === 'list_detail' && <div className="rule-subsection pagination-workbench"><div className="rule-subsection-heading"><h4>{t('config.rule.pagination')}</h4></div><div className="pagination-editor"><label><span>{t('config.editor.method')}</span><Select value={draft.paginationType} onValueChange={(value) => setDraft((current) => ({ ...current, paginationType: value as RuleEditorDraft['paginationType'] }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="next_link">{t('config.editor.nextLink')}</SelectItem><SelectItem value="page">{t('config.editor.pageParam')}</SelectItem></SelectContent></Select></label>{draft.paginationType === 'next_link' ? <label className="pagination-selector"><span>{t('config.editor.nextLinkSelector')}</span><Input aria-label={t('config.editor.nextLinkSelector')} className="selector-input" value={draft.paginationSelector} onChange={(event) => setDraft((current) => ({ ...current, paginationSelector: event.target.value }))} /></label> : <><label><span>{t('config.editor.parameterName')}</span><Input value={draft.pageParameter} onChange={(event) => setDraft((current) => ({ ...current, pageParameter: event.target.value }))} /></label><label><span>{t('config.editor.pageStart')}</span><Input type="number" min={0} value={draft.pageStart} onChange={(event) => setDraft((current) => ({ ...current, pageStart: Number(event.target.value) }))} /></label><label><span>{t('config.editor.pageStep')}</span><Input type="number" min={1} value={draft.pageStep} onChange={(event) => setDraft((current) => ({ ...current, pageStep: Number(event.target.value) }))} /></label></>}<label><span>{t('config.editor.maxPages')}</span><Input type="number" min={1} max={100000} value={draft.maxPages} onChange={(event) => setDraft((current) => ({ ...current, maxPages: Number(event.target.value) }))} /></label>{draft.paginationType === 'page' && <label className="pagination-check"><Checkbox checked={draft.stopWhenNoItems} onCheckedChange={(checked) => setDraft((current) => ({ ...current, stopWhenNoItems: checked === true }))} /><span>{t('config.editor.stopWhenNoItems')}</span></label>}</div></div>}
              {candidate.mode === 'single' && <div className="rule-subsection"><div className="rule-subsection-heading"><h4>{t('config.editor.outputFields')}</h4></div><div className="rule-field-editor-list">{draft.detailFields.map((field, index) => <RuleFieldEditor key={field.key} field={field} onChange={(selector) => setField('detailFields', index, selector)} />)}</div></div>}
            </div>
          </section>
          {candidate.mode === 'list_detail' && <>
            <div className="rule-stage-bridge"><code>detailUrl</code><ArrowRight /><span>{t('flow.detailCollection')}</span></div>
            <section className="rule-stage-section detail-rule-stage">
              <div className="rule-stage-marker"><span>2</span></div>
              <div className="rule-stage-content">
                <header><h3>{t('flow.detailCollection')}</h3></header>
                <div className="rule-subsection"><div className="rule-subsection-heading"><h4>{t('config.editor.outputFields')}</h4></div><div className="rule-field-editor-list">{draft.detailFields.map((field, index) => <RuleFieldEditor key={field.key} field={field} onChange={(selector) => setField('detailFields', index, selector)} />)}</div></div>
              </div>
            </section>
          </>}
      </div>
      <div className="rule-editor-footer"><strong>{changed ? t('config.editor.changeCount', { total: changeCount }) : t('config.editor.noChanges')}</strong><DialogFooter><Button variant="ghost" onClick={() => setDialogOpen(false)} disabled={pending}>{t('common:action.cancel')}</Button><Button onClick={() => void submit()} disabled={!changed || !valid || pending}>{pending ? <LoaderCircle className="animate-spin" /> : <Save />}{pending ? t('config.editor.saving') : t('config.editor.saveAsCandidate')}</Button></DialogFooter></div>
        </TabsContent>
        <TabsContent value="contract" className="rule-editor-contract-panel"><ScrollArea className="rule-editor-contract-scroll"><pre className="contract-preview">{JSON.stringify(candidate.gatherSpec, null, 2)}</pre></ScrollArea></TabsContent>
      </Tabs>
    </DialogContent>
  </Dialog>
}

type SchedulePreset = 'every_6h' | 'daily' | 'weekdays' | 'weekly' | 'custom'

type ScheduleDraft = {
  enabled: boolean
  preset: SchedulePreset
  time: string
  weekday: string
  customCron: string
}

function scheduleDraft(schedule: CollectorSchedule): ScheduleDraft {
  const parts = schedule.cronExpression.trim().split(/\s+/)
  const time = parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])
    ? `${parts[1].padStart(2, '0')}:${parts[0].padStart(2, '0')}`
    : '08:00'
  const preset: SchedulePreset = schedule.cronExpression === '0 */6 * * *'
    ? 'every_6h'
    : parts[4] === '1-5'
      ? 'weekdays'
      : /^\d$/.test(parts[4] ?? '')
        ? 'weekly'
        : parts[2] === '*' && parts[3] === '*' && parts[4] === '*'
          ? 'daily'
          : 'custom'
  return { enabled: schedule.enabled, preset, time, weekday: /^\d$/.test(parts[4] ?? '') ? parts[4] : '1', customCron: schedule.cronExpression }
}

function cronForDraft(draft: ScheduleDraft) {
  if (draft.preset === 'every_6h') return '0 */6 * * *'
  if (draft.preset === 'custom') return draft.customCron.trim()
  const [hour = '8', minute = '0'] = draft.time.split(':')
  const day = draft.preset === 'weekdays' ? '1-5' : draft.preset === 'weekly' ? draft.weekday : '*'
  return `${Number(minute)} ${Number(hour)} * * ${day}`
}

function scheduleLabel(cron: string, t: Translator) {
  const parts = cron.trim().split(/\s+/)
  if (cron === '0 */6 * * *') return t('schedule.every6h')
  if (parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])) {
    const time = `${parts[1].padStart(2, '0')}:${parts[0].padStart(2, '0')}`
    if (parts[4] === '*') return t('schedule.dailyAt', { time })
    if (parts[4] === '1-5') return t('schedule.weekdaysAt', { time })
    const weekday = [0, 1, 2, 3, 4, 5, 6].map((day) => t(`schedule.weekday.${day}`))[Number(parts[4])]
    if (weekday) return t('schedule.weekdayAt', { weekday, time })
  }
  return t('schedule.customCron', { cron })
}

function scheduleTime(value: string | null, t: Translator) {
  if (!value) return t('schedule.pendingCalculation')
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value))
}

function SchedulePanel({ schedule, disabled, pending, onSave }: {
  schedule: CollectorSchedule
  disabled: boolean
  pending: boolean
  onSave: (input: CollectorScheduleInput) => void
}) {
  const { t } = useTranslation('collectorDetail')
  const initial = scheduleDraft(schedule)
  const [draft, setDraft] = useState<ScheduleDraft>(initial)
  const [open, setOpen] = useState(false)
  const cronExpression = cronForDraft(draft)
  const input: CollectorScheduleInput = { enabled: draft.enabled, cronExpression, timezone: 'Asia/Shanghai', overlapPolicy: 'forbid' }
  const current: CollectorScheduleInput = { enabled: schedule.enabled, cronExpression: schedule.cronExpression, timezone: schedule.timezone, overlapPolicy: schedule.overlapPolicy }
  const changed = JSON.stringify(input) !== JSON.stringify(current)
  const valid = cronExpression.trim().split(/\s+/).length === 5

  function setDialogOpen(next: boolean) {
    if (next) setDraft(scheduleDraft(schedule))
    setOpen(next)
  }

  function submit() {
    onSave(input)
    setOpen(false)
  }

  return <section className="schedule-panel" aria-label={t('schedule.panelAria')}>
    <div className="collection-policy-heading">
      <span className="policy-icon schedule-icon"><CalendarClock /></span>
      <div><span className="eyebrow">RUN SCHEDULE</span><h2>{t('schedule.title')}</h2><p>{t('schedule.description')}</p></div>
      <Dialog open={open} onOpenChange={setDialogOpen}><DialogTrigger asChild><Button variant="outline" size="sm" disabled={disabled}><Pencil />{t('schedule.configure')}</Button></DialogTrigger><DialogContent className="schedule-dialog"><DialogHeader><DialogTitle>{t('schedule.dialogTitle')}</DialogTitle><DialogDescription>{t('schedule.dialogDescription')}</DialogDescription></DialogHeader>
        <div className="schedule-controls">
          <label className="schedule-enabled"><Checkbox checked={draft.enabled} onCheckedChange={(checked) => setDraft((currentDraft) => ({ ...currentDraft, enabled: checked === true }))} /><span><strong>{t('schedule.enableAuto')}</strong><small>{t('schedule.enableAutoHint')}</small></span></label>
          <label><span>{t('schedule.frequency')}</span><Select value={draft.preset} onValueChange={(value) => setDraft((currentDraft) => ({ ...currentDraft, preset: value as SchedulePreset }))} disabled={!draft.enabled}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="every_6h">{t('schedule.every6h')}</SelectItem><SelectItem value="daily">{t('schedule.daily')}</SelectItem><SelectItem value="weekdays">{t('schedule.weekdays')}</SelectItem><SelectItem value="weekly">{t('schedule.weekly')}</SelectItem><SelectItem value="custom">{t('schedule.custom')}</SelectItem></SelectContent></Select></label>
          {draft.preset !== 'every_6h' && draft.preset !== 'custom' && <label><span>{t('schedule.time')}</span><Input type="time" value={draft.time} onChange={(event) => setDraft((currentDraft) => ({ ...currentDraft, time: event.target.value }))} disabled={!draft.enabled} /></label>}
          {draft.preset === 'weekly' && <label><span>{t('schedule.weekdayLabel')}</span><Select value={draft.weekday} onValueChange={(value) => setDraft((currentDraft) => ({ ...currentDraft, weekday: value }))} disabled={!draft.enabled}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="1">{t('schedule.weekday.1')}</SelectItem><SelectItem value="2">{t('schedule.weekday.2')}</SelectItem><SelectItem value="3">{t('schedule.weekday.3')}</SelectItem><SelectItem value="4">{t('schedule.weekday.4')}</SelectItem><SelectItem value="5">{t('schedule.weekday.5')}</SelectItem><SelectItem value="6">{t('schedule.weekday.6')}</SelectItem><SelectItem value="0">{t('schedule.weekday.0')}</SelectItem></SelectContent></Select></label>}
          {draft.preset === 'custom' && <label className="schedule-custom-cron"><span>{t('schedule.cronExpression')}</span><Input className="selector-input" value={draft.customCron} onChange={(event) => setDraft((currentDraft) => ({ ...currentDraft, customCron: event.target.value }))} placeholder="0 8 * * *" disabled={!draft.enabled} /><small>{t('schedule.cronFormatHint')}</small></label>}
          <div className="schedule-guardrails"><span><small>{t('schedule.timezone')}</small><strong>{t('schedule.timezoneValue')}</strong></span><span><small>{t('schedule.conflict')}</small><strong>{t('schedule.skipConflict')}</strong></span><span><small>{t('schedule.actualCron')}</small><code>{cronExpression}</code></span></div>
        </div>
        <DialogFooter><DialogClose asChild><Button variant="ghost">{t('common:action.cancel')}</Button></DialogClose><Button onClick={submit} disabled={disabled || !changed || !valid}>{pending ? <LoaderCircle className="animate-spin" /> : <Save />}{pending ? t('schedule.saving') : t('schedule.save')}</Button></DialogFooter>
      </DialogContent></Dialog>
    </div>
    <div className="policy-summary-grid schedule-summary-grid">
      <span><small>{t('schedule.statusLabel')}</small><strong>{schedule.enabled ? t('schedule.autoEnabled') : t('schedule.manualOnly')}</strong></span>
      <span><small>{t('schedule.frequencyLabel')}</small><strong>{schedule.enabled ? scheduleLabel(schedule.cronExpression, t) : t('schedule.notSet')}</strong></span>
      <span><small>{t('schedule.nextRun')}</small><strong>{schedule.enabled ? scheduleTime(schedule.nextRunAt, t) : '—'}</strong></span>
      <span><small>{t('schedule.conflict')}</small><strong>{t('schedule.skipWhenRunning')}</strong></span>
    </div>
  </section>
}

function CollectionPolicyPanel({
  policy,
  disabled,
  pending,
  onSave,
}: {
  policy: CollectionPolicy | null
  disabled: boolean
  pending: boolean
  onSave: (input: CollectionPolicyInput) => void
}) {
  const { t } = useTranslation('collectorDetail')
  const initial: CollectionPolicyInput = policy
    ? {
        mode: policy.mode,
        initialWindowDays: policy.initialWindowDays,
        lookbackDays: policy.lookbackDays,
        consecutiveOlderPages: policy.consecutiveOlderPages,
        maxPages: policy.maxPages,
        maxItems: policy.maxItems,
        timezone: policy.timezone,
      }
    : {
        mode: 'rolling_incremental',
        initialWindowDays: 30,
        lookbackDays: 3,
        consecutiveOlderPages: 2,
        maxPages: 20,
        maxItems: 300,
        timezone: 'Asia/Shanghai',
      }
  const [draft, setDraft] = useState<CollectionPolicyInput>(initial)
  const [open, setOpen] = useState(false)
  const changed = JSON.stringify(draft) !== JSON.stringify(initial)
  const setNumber = (key: keyof CollectionPolicyInput, value: string) => {
    const parsed = Number(value)
    if (Number.isInteger(parsed)) setDraft((current) => ({ ...current, [key]: parsed }))
  }

  function setDialogOpen(next: boolean) {
    if (next) setDraft(initial)
    setOpen(next)
  }

  function submit() {
    onSave(draft)
    setOpen(false)
  }

  return (
    <section className="collection-policy-panel" aria-label={t('policy.panelAria')}>
      <div className="collection-policy-heading">
        <span className="policy-icon"><CalendarRange /></span>
        <div><span className="eyebrow">COLLECTION POLICY</span><h2>{t('policy.title')}</h2><p>{t('policy.description')}</p></div>
        <div className="policy-heading-actions"><Dialog open={open} onOpenChange={setDialogOpen}><DialogTrigger asChild><Button variant="outline" size="sm" disabled={disabled}><Pencil />{t('policy.edit')}</Button></DialogTrigger><DialogContent className="policy-dialog"><DialogHeader><DialogTitle>{t('policy.dialogTitle')}</DialogTitle><DialogDescription>{t('policy.dialogDescription')}</DialogDescription></DialogHeader><div className="policy-controls">
          <label><span>{t('policy.initialWindow')}</span><Select value={String(draft.initialWindowDays)} onValueChange={(value) => setNumber('initialWindowDays', value)} disabled={disabled}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="7">{t('policy.recentDays', { days: 7 })}</SelectItem><SelectItem value="30">{t('policy.recentDays', { days: 30 })}</SelectItem><SelectItem value="90">{t('policy.recentDays', { days: 90 })}</SelectItem><SelectItem value="180">{t('policy.recentDays', { days: 180 })}</SelectItem></SelectContent></Select></label>
          <label><span>{t('policy.lookback')}</span><div className="number-control"><Input type="number" min={0} max={90} value={draft.lookbackDays} onChange={(event) => setNumber('lookbackDays', event.target.value)} disabled={disabled} /><small>{t('policy.unit.days')}</small></div></label>
          <label><span>{t('policy.stopAfterOldPages')}</span><div className="number-control"><Input type="number" min={1} max={10} value={draft.consecutiveOlderPages} onChange={(event) => setNumber('consecutiveOlderPages', event.target.value)} disabled={disabled} /><small>{t('policy.unit.pages')}</small></div></label>
          <label><span>{t('policy.maxPages')}</span><div className="number-control"><Input type="number" min={1} max={1000} value={draft.maxPages} onChange={(event) => setNumber('maxPages', event.target.value)} disabled={disabled} /><small>{t('policy.unit.pages')}</small></div></label>
          <label><span>{t('policy.maxItems')}</span><div className="number-control"><Input type="number" min={1} max={100000} value={draft.maxItems} onChange={(event) => setNumber('maxItems', event.target.value)} disabled={disabled} /><small>{t('policy.unit.items')}</small></div></label>
        </div><DialogFooter><DialogClose asChild><Button variant="ghost">{t('common:action.cancel')}</Button></DialogClose><Button onClick={submit} disabled={disabled || !changed}>{pending ? <LoaderCircle className="animate-spin" /> : <Save />}{pending ? t('policy.saving') : t('policy.save')}</Button></DialogFooter></DialogContent></Dialog></div>
      </div>
      <div className="policy-summary-grid">
        <span><small>{t('policy.initialWindow')}</small><strong>{t('policy.recentDays', { days: initial.initialWindowDays })}</strong></span>
        <span><small>{t('policy.lookback')}</small><strong>{t('policy.daysValue', { days: initial.lookbackDays })}</strong></span>
        <span><small>{t('policy.stopCondition')}</small><strong>{t('policy.consecutiveOldPages', { total: initial.consecutiveOlderPages })}</strong></span>
        <span><small>{t('policy.runLimit')}</small><strong>{t('policy.runLimitValue', { pages: initial.maxPages, items: initial.maxItems })}</strong></span>
      </div>
    </section>
  )
}

const deliveryToneClasses = {
  neutral: 'border-[#d9e0e3] bg-[#eef2f3] text-[#526169]',
  info: 'border-[#bad0ff] bg-[#edf3ff] text-[#2557d6]',
  success: 'border-[#b6decf] bg-[#eaf7f2] text-[#117153]',
  warning: 'border-[#efd3a8] bg-[#fff6e8] text-[#9b5907]',
  danger: 'border-[#efc1c1] bg-[#fff0f0] text-[#aa3030]',
}

function deliveryStatusTone(status: DeliveryStatus): keyof typeof deliveryToneClasses {
  if (status === 'delivered') return 'success'
  if (status === 'failed') return 'warning'
  if (status === 'dead_lettered') return 'danger'
  return 'info'
}

function DeliveryStatusBadge({ status }: { status: DeliveryStatus }) {
  const { t } = useTranslation('collectors')
  return (
    <Badge variant="outline" className={cn('gap-1 rounded-md px-1.5 py-0.5 font-medium', deliveryToneClasses[deliveryStatusTone(status)])}>
      {t(`delivery.status.${status}`)}
    </Badge>
  )
}

function deliveryTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value))
}

function deliveryAttemptSummary(delivery: DeliverySummary, t: TFunction<'collectors', undefined>) {
  const statusCode = delivery.latestAttempt?.statusCode ?? delivery.lastStatusCode
  const error = delivery.latestAttempt?.error ?? delivery.lastError
  const time = delivery.latestAttempt?.finishedAt ?? delivery.updatedAt
  if (statusCode === null && !error) return t('delivery.noAttempt')
  return [statusCode ?? t('delivery.noStatusCode'), error, deliveryTime(time)].filter(Boolean).join(' · ')
}

function WebhookPushPanel({ collectorId }: { collectorId: string }) {
  const { t } = useTranslation('collectors')
  const queryClient = useQueryClient()
  const sinksQuery = useQuery({ queryKey: ['sinks', collectorId], queryFn: () => api.sinks(collectorId) })
  const [editing, setEditing] = useState<'new' | Sink | null>(null)
  const [deleting, setDeleting] = useState<Sink | null>(null)
  const [testQueued, setTestQueued] = useState(false)
  const testSink = useMutation({
    mutationFn: (sinkId: string) => api.testSink(collectorId, sinkId),
    onSuccess: () => {
      setTestQueued(true)
      queryClient.invalidateQueries({ queryKey: ['deliveries', collectorId] })
    },
  })
  const sinks = sinksQuery.data ?? []

  return (
    <section className="collection-policy-panel" aria-label={t('webhook.panelAria')}>
      <div className="collection-policy-heading">
        <span className="policy-icon"><Webhook /></span>
        <div><span className="eyebrow">WEBHOOK DELIVERY</span><h2>{t('webhook.title')}</h2><p>{t('webhook.description')}</p></div>
        <Button variant="outline" size="sm" onClick={() => setEditing('new')}><Plus />{t('webhook.add')}</Button>
      </div>
      {testSink.isSuccess && testQueued && <Alert className="mb-3"><Send /><AlertTitle>{t('webhook.testQueued')}</AlertTitle></Alert>}
      {testSink.error && <Alert variant="destructive" className="mb-3"><AlertTitle>{testSink.error.message}</AlertTitle></Alert>}
      {sinksQuery.error && <Alert variant="destructive" className="mb-3"><AlertTitle>{sinksQuery.error.message}</AlertTitle></Alert>}
      {sinksQuery.isLoading && <Skeleton className="h-16 w-full" />}
      {sinksQuery.isSuccess && sinks.length === 0 && <div className="card-empty">{t('webhook.empty')}</div>}
      {sinks.map((sink) => (
        <div className="flex items-center gap-3 border-t border-[#e0e6e8] py-2.5" key={sink.id}>
          <div className="min-w-0 flex-1">
            <code className="block truncate text-sm" title={sink.url}>{sink.url}</code>
            <div className="mt-1 flex items-center gap-2 text-xs text-[#76848b]">
              <Badge variant="outline" className={cn('rounded-md px-1.5 py-0.5 font-medium', sink.enabled ? deliveryToneClasses.success : deliveryToneClasses.neutral)}>
                {sink.enabled ? t('webhook.enabledOn') : t('webhook.enabledOff')}
              </Badge>
              <span>{t('webhook.version', { version: sink.version })}</span>
              <span className={sink.credentialConfigured ? '' : 'text-[#9b5907]'}>{sink.credentialConfigured ? t('webhook.credentialConfigured') : t('webhook.credentialMissing')}</span>
            </div>
          </div>
          <Button variant="outline" size="sm" disabled={testSink.isPending} aria-label={t('webhook.testAria', { url: sink.url })} onClick={() => testSink.mutate(sink.id)}>
            {testSink.isPending ? <LoaderCircle className="animate-spin" /> : <Send />}{t('webhook.test')}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t('webhook.actionsAria', { url: sink.url })}><MoreHorizontal /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setEditing(sink)}><Pencil />{t('webhook.edit')}</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setDeleting(sink)}><Trash2 />{t('webhook.delete')}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ))}
      {editing && <SinkDialog key={editing === 'new' ? 'new' : editing.id} collectorId={collectorId} sink={editing} onClose={() => setEditing(null)} />}
      {deleting && <SinkDeleteDialog key={deleting.id} collectorId={collectorId} sink={deleting} onClose={() => setDeleting(null)} />}
    </section>
  )
}

function SinkDialog({ collectorId, sink, onClose }: { collectorId: string; sink: 'new' | Sink; onClose: () => void }) {
  const { t } = useTranslation('collectors')
  const queryClient = useQueryClient()
  const isEdit = sink !== 'new'
  const [url, setUrl] = useState(isEdit ? sink.url : '')
  const [secret, setSecret] = useState('')
  const [enabled, setEnabled] = useState(isEdit ? sink.enabled : true)
  const [showSecret, setShowSecret] = useState(false)
  const save = useMutation({
    mutationFn: () => {
      const trimmedUrl = url.trim()
      const trimmedSecret = secret.trim()
      if (isEdit) {
        const input: SinkUpdateInput = { url: trimmedUrl, enabled }
        if (trimmedSecret) input.secret = trimmedSecret
        return api.updateSink(collectorId, sink.id, input)
      }
      const input: SinkInput = { type: 'webhook', url: trimmedUrl, enabled }
      if (trimmedSecret) input.secret = trimmedSecret
      return api.createSink(collectorId, input)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sinks', collectorId] })
      onClose()
    },
  })
  const errorMessage = save.error instanceof ApiRequestError && save.error.code === 'INVALID_URL'
    ? t('webhook.invalidUrl')
    : save.error?.message

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="webhook-dialog">
        <DialogHeader>
          <DialogTitle>{isEdit ? t('webhook.dialogEditTitle') : t('webhook.dialogAddTitle')}</DialogTitle>
          <DialogDescription>{t('webhook.dialogDescription')}</DialogDescription>
        </DialogHeader>
        <form id="sink-settings-form" className="definition-form" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
          <label><span>{t('webhook.url')}</span><Input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder={t('webhook.urlPlaceholder')} required /></label>
          <div className="field-group">
            <label htmlFor="sink-secret">{t('webhook.secret')}</label>
            <div className="credential-input">
              <KeyRound />
              <Input
                id="sink-secret"
                type={showSecret ? 'text' : 'password'}
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
                placeholder={isEdit && sink.credentialConfigured ? t('webhook.secretKeep') : t('webhook.secretPlaceholder')}
                autoComplete="new-password"
              />
              <Button type="button" variant="ghost" size="icon-sm" aria-label={showSecret ? t('webhook.hideSecret') : t('webhook.showSecret')} onClick={() => setShowSecret((visible) => !visible)}>
                {showSecret ? <EyeOff /> : <Eye />}
              </Button>
            </div>
            <small className="credential-help">{isEdit && sink.credentialConfigured ? t('webhook.secretKeep') : t('webhook.secretHelp')}</small>
          </div>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={enabled} onCheckedChange={(checked) => setEnabled(checked === true)} /><span>{t('webhook.enabled')}</span></label>
        </form>
        {save.error && <Alert variant="destructive"><AlertTitle>{t('webhook.saveFailed', { message: errorMessage })}</AlertTitle></Alert>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>{t('common:action.cancel')}</Button>
          <Button type="submit" form="sink-settings-form" disabled={!url.trim() || save.isPending}>{save.isPending ? <LoaderCircle className="animate-spin" /> : <Save />}{save.isPending ? t('webhook.saving') : t('webhook.save')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SinkDeleteDialog({ collectorId, sink, onClose }: { collectorId: string; sink: Sink; onClose: () => void }) {
  const { t } = useTranslation('collectors')
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => api.deleteSink(collectorId, sink.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sinks', collectorId] })
      onClose()
    },
  })
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('webhook.confirmDeleteTitle')}</DialogTitle>
          <DialogDescription>{t('webhook.confirmDeleteDescription', { url: sink.url })}</DialogDescription>
        </DialogHeader>
        {remove.error && <Alert variant="destructive"><AlertTitle>{remove.error.message}</AlertTitle></Alert>}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={remove.isPending}>{t('common:action.cancel')}</Button>
          <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>{remove.isPending ? <LoaderCircle className="animate-spin" /> : <Trash2 />}{t('webhook.confirmDelete')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeliveryLogPanel({ collectorId }: { collectorId: string }) {
  const { t } = useTranslation('collectors')
  const queryClient = useQueryClient()
  const deliveriesQuery = useQuery({ queryKey: ['deliveries', collectorId], queryFn: () => api.deliveries(collectorId) })
  const sinksQuery = useQuery({ queryKey: ['sinks', collectorId], queryFn: () => api.sinks(collectorId) })
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const redeliver = useMutation({
    mutationFn: (id: string) => api.redeliverDelivery(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deliveries', collectorId] })
      setExpandedId(null)
    },
  })
  const deliveries = deliveriesQuery.data ?? []
  const sinkUrl = (sinkId: string) => (sinksQuery.data ?? []).find((sink) => sink.id === sinkId)?.url

  return (
    <section className="collection-policy-panel" aria-label={t('delivery.panelAria')}>
      <div className="collection-policy-heading">
        <span className="policy-icon schedule-icon"><Inbox /></span>
        <div><span className="eyebrow">DELIVERY LOG</span><h2>{t('delivery.title')}</h2><p>{t('delivery.description')}</p></div>
      </div>
      {deliveriesQuery.error && <Alert variant="destructive" className="mb-3"><AlertTitle>{deliveriesQuery.error.message}</AlertTitle></Alert>}
      {deliveriesQuery.isLoading && <Skeleton className="h-20 w-full" />}
      {deliveriesQuery.isSuccess && deliveries.length === 0 && <div className="card-empty">{t('delivery.empty')}</div>}
      {deliveries.length > 0 && (
        <div>
          <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto_minmax(0,1.2fr)_auto] items-center gap-3 border-b border-[#e0e6e8] pb-1.5 text-xs text-[#76848b]" aria-hidden="true">
            <span>{t('delivery.event')}</span><span>{t('delivery.target')}</span><span>{t('delivery.statusLabel')}</span><span>{t('delivery.lastAttempt')}</span><span />
          </div>
          {deliveries.map((delivery) => (
            <DeliveryRow
              key={delivery.id}
              delivery={delivery}
              sinkUrl={sinkUrl(delivery.sinkId)}
              redeliverPending={redeliver.isPending && redeliver.variables === delivery.id}
              expanded={expandedId === delivery.id}
              onToggle={() => setExpandedId((current) => current === delivery.id ? null : delivery.id)}
              onRedeliver={() => redeliver.mutate(delivery.id)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function DeliveryRow({ delivery, sinkUrl, redeliverPending, expanded, onToggle, onRedeliver }: {
  delivery: DeliverySummary
  sinkUrl: string | undefined
  redeliverPending: boolean
  expanded: boolean
  onToggle: () => void
  onRedeliver: () => void
}) {
  const { t } = useTranslation('collectors')
  return (
    <div className="border-b border-[#e0e6e8] last:border-b-0">
      <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto_minmax(0,1.2fr)_auto] items-center gap-3 py-2.5">
        <div className="flex min-w-0 items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label={t('delivery.expandAria', { id: delivery.id })} aria-expanded={expanded} onClick={onToggle}>
            <ChevronDown className={cn('transition-transform', expanded && 'rotate-180')} />
          </Button>
          <code className="truncate text-xs" title={delivery.itemEventId}>{delivery.itemEventId}</code>
          {delivery.kind === 'test' && <Badge variant="outline" className="shrink-0 rounded-md px-1.5 py-0.5 text-xs font-medium">{t('delivery.testTag')}</Badge>}
        </div>
        <span className="truncate text-xs text-[#76848b]" title={sinkUrl}>{sinkUrl ?? delivery.sinkId}</span>
        <DeliveryStatusBadge status={delivery.status} />
        <span className="truncate text-xs text-[#76848b]" title={deliveryAttemptSummary(delivery, t)}>{deliveryAttemptSummary(delivery, t)}</span>
        <div className="flex items-center justify-end gap-1">
          {delivery.status === 'dead_lettered' && (
            <Button variant="outline" size="sm" disabled={redeliverPending} aria-label={t('delivery.redeliverAria', { id: delivery.id })} onClick={onRedeliver}>
              {redeliverPending ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}{redeliverPending ? t('delivery.redelivering') : t('delivery.redeliver')}
            </Button>
          )}
        </div>
      </div>
      {expanded && <DeliveryAttempts deliveryId={delivery.id} />}
    </div>
  )
}

function DeliveryAttempts({ deliveryId }: { deliveryId: string }) {
  const { t } = useTranslation('collectors')
  const detailQuery = useQuery({ queryKey: ['delivery', deliveryId], queryFn: () => api.delivery(deliveryId) })
  const attempts = detailQuery.data?.attempts ?? []
  return (
    <div className="mb-3 ml-8 rounded-md border border-[#e0e6e8] bg-[#f7f9fa] p-3">
      <p className="mb-2 text-xs font-medium text-[#526169]">{t('delivery.attemptsTitle')}</p>
      {detailQuery.isLoading && <Skeleton className="h-8 w-full" />}
      {detailQuery.isError && <p className="text-xs text-[#aa3030]">{detailQuery.error.message}</p>}
      {detailQuery.isSuccess && attempts.length === 0 && <p className="text-xs text-[#76848b]">{t('delivery.noAttempts')}</p>}
      <ul className="space-y-1.5">
        {attempts.map((attempt) => (
          <li className="flex items-center gap-3 text-xs" key={attempt.id}>
            <span className="shrink-0 font-medium text-[#526169]">{t('delivery.attemptNo', { no: attempt.attemptNo })}</span>
            <span className="shrink-0 text-[#76848b]">{t('delivery.attemptTime', { started: deliveryTime(attempt.startedAt), finished: deliveryTime(attempt.finishedAt) })}</span>
            <span className={cn('shrink-0 font-medium', attempt.statusCode === null || attempt.statusCode < 400 ? 'text-[#117153]' : 'text-[#aa3030]')}>{attempt.statusCode ?? t('delivery.noStatusCode')}</span>
            {attempt.error && <span className="truncate text-[#aa3030]" title={attempt.error}>{attempt.error}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

const singleStageLabelKeys = ['explore.stage.queued', 'explore.stage.fetch', 'explore.stage.validate', 'explore.stage.finale'] as const
const listStageLabelKeys = ['explore.stageList.queued', 'explore.stageList.listPages', 'explore.stageList.detailDiscovery', 'explore.stageList.detailFetch', 'explore.stageList.validate', 'explore.stageList.finale'] as const

function ExplorationProgress({ operation, singleStage }: { operation?: Operation; singleStage: boolean }) {
  const { t } = useTranslation('collectorDetail')
  const phase = operation?.phase ?? 'queued'
  const copy = {
    queued: [t('explore.phase.queued.title'), t('explore.phase.queued.detail')],
    fetching_list: [singleStage ? t('explore.phase.fetchingList.titleSingle') : t('explore.phase.fetchingList.titleList'), t('explore.phase.fetchingList.detail')],
    discovering_details: [t('explore.phase.discoveringDetails.title'), t('explore.phase.discoveringDetails.detail')],
    fetching_details: [t('explore.phase.fetchingDetails.title'), t('explore.phase.fetchingDetails.detail')],
    validating: [singleStage ? t('explore.phase.validating.titleSingle') : t('explore.phase.validating.titleList'), t('explore.phase.validating.detail')],
    finalizing: [t('explore.phase.finalizing.title'), t('explore.phase.finalizing.detail')],
    completed: [t('explore.phase.completed.title'), t('explore.phase.completed.detail')],
  } as const
  const [title, detail] = copy[phase]
  const phases = singleStage
    ? ['queued', 'fetching_list', 'validating', 'completed']
    : ['queued', 'fetching_list', 'discovering_details', 'fetching_details', 'validating', 'completed']
  const labels = (singleStage ? singleStageLabelKeys : listStageLabelKeys).map((key) => t(key))
  const currentIndex = Math.max(0, phases.indexOf(phase))
  return <div className="workbench-content progress-view" aria-live="polite"><span className="pulse-icon"><LoaderCircle className="animate-spin" /></span><div><span className="eyebrow">CRAWL4AI · {phase.toUpperCase()}</span><h2>{title}</h2><p>{detail}</p></div><Progress value={operation?.progress ?? 6} /><div className="progress-steps">{labels.map((label, index) => <span className={index === currentIndex ? 'active' : index < currentIndex ? 'done' : ''} key={label}>{index <= currentIndex ? <Check /> : <LoaderCircle />}{label}</span>)}</div></div>
}

function RunProgress({ operation }: { operation?: Operation }) {
  const { t } = useTranslation('collectorDetail')
  const phase = operation?.phase ?? 'queued'
  const copy = {
    queued: [t('runs.phase.queued.title'), t('runs.phase.queued.detail')],
    fetching_list: [t('runs.phase.fetchingList.title'), t('runs.phase.fetchingList.detail')],
    discovering_details: [t('runs.phase.discoveringDetails.title'), t('runs.phase.discoveringDetails.detail')],
    fetching_details: [t('runs.phase.fetchingDetails.title'), t('runs.phase.fetchingDetails.detail')],
    validating: [t('runs.phase.validating.title'), t('runs.phase.validating.detail')],
    finalizing: [t('runs.phase.finalizing.title'), t('runs.phase.finalizing.detail')],
    completed: [t('runs.phase.completed.title'), t('runs.phase.completed.detail')],
  } as const
  const [title, detail] = copy[phase]
  const metrics = operation?.metrics
  return <div className="workbench-content progress-view" aria-live="polite"><span className="pulse-icon blue"><Play /></span><div><span className="eyebrow">CRAWLEE · {phase.toUpperCase()}</span><h2>{title}</h2><p>{detail}</p></div><Progress value={operation?.progress ?? 6} /><div className="metric-strip"><span><strong>{metrics?.listPagesFetched ?? 0}</strong> {t('runs.metrics.listPages')}</span><span><strong>{metrics?.detailUrlsDiscovered ?? 0}</strong> {t('runs.metrics.detailUrls')}</span><span><strong>{metrics?.detailPagesFetched ?? 0}</strong> {t('runs.metrics.detailPages')}</span><span><strong>{metrics?.warningCount ?? 0}</strong> {t('common:evidence.qualityWarning')}</span></div></div>
}

interface ReviewWorkspaceProps {
  candidate: CandidateRule
  previewItems: HarvestItem[]
  selectedField?: CandidateField
  decisions: Record<string, FieldReviewDecision>
  onSelectField: (field: CandidateField) => void
  onSelectItem: (item: HarvestItem) => void
  onDecision: (key: string, decision: FieldReviewDecision) => void
}

function ReviewWorkspace({ candidate, previewItems, selectedField, decisions, onSelectField, onSelectItem, onDecision }: ReviewWorkspaceProps) {
  const { t } = useTranslation('collectorDetail')
  const decided = candidate.fields.filter((field) => (decisions[field.key] ?? 'pending') !== 'pending').length
  const unresolvedWarnings = candidate.fields.filter((field) => field.warning && (decisions[field.key] ?? 'pending') === 'pending')
  const pending = candidate.fields.length - decided
  return (
    <div className="review-workspace">
      {unresolvedWarnings.length > 0 ? <section className="review-blocker"><span className="review-blocker-icon"><CircleAlert /></span><div><span className="eyebrow">BLOCKING REVIEW</span><h2>{t('review.blockingTitle', { total: unresolvedWarnings.length })}</h2><p><strong>{unresolvedWarnings.map((field) => field.label).join(t('review.warningJoin'))}</strong>{t('review.blockingDetail', { warning: unresolvedWarnings[0].warning })}</p></div><Button variant="outline" onClick={() => onSelectField(unresolvedWarnings[0])}><PanelRightOpen />{t('review.viewEvidence')}</Button></section> : <section className="review-blocker is-clear"><span className="review-blocker-icon"><ShieldCheck /></span><div><span className="eyebrow">READY TO PUBLISH</span><h2>{t('review.clearTitle')}</h2><p>{t('review.clearDescription')}</p></div></section>}
      <div className="review-summary-strip" aria-label={t('review.summaryAria')}>
        <span><strong>{candidate.fields.length}</strong><small>{t('review.fieldsLabel')}</small></span>
        <span><strong>{decided}</strong><small>{t('review.decidedLabel')}</small></span>
        <span className={pending > 0 ? 'attention' : ''}><strong>{pending}</strong><small>{t('review.pendingLabel')}</small></span>
        <span><strong>{candidate.discovery.detailPagesValidated}/{candidate.discovery.detailPagesValidated}</strong><small>{t('review.validatedSamples')}</small></span>
      </div>
      <Tabs defaultValue="fields" className="review-content-tabs">
        <TabsList variant="line"><TabsTrigger value="fields">{t('review.fieldsTab')}</TabsTrigger><TabsTrigger value="samples">{t('review.samplesTab')} <span className="tab-count neutral">{previewItems.length}</span></TabsTrigger></TabsList>
        <TabsContent value="fields">
          <section className="review-field-section">
            <div className="section-heading"><div><span className="eyebrow">CANDIDATE FIELDS</span><h2>{t('review.sectionTitle')}</h2><p>{t('review.sectionDescription')}</p></div><span className="review-count">{t('review.decidedCount', { decided, total: candidate.fields.length })}</span></div>
            <div className="field-table review-field-table">
              <div className="field-table-head"><span>{t('review.fieldsLabel')}</span><span>{t('common:evidence.extractSample')}</span><span>{t('common:evidence.confidence')}</span><span>{t('common:evidence.reviewDecision')}</span><span aria-hidden="true" /></div>
              {candidate.fields.map((field) => (
                <div className={`field-row ${selectedField?.key === field.key ? 'is-selected' : ''}`} key={field.key}>
                  <div className="field-name-button"><strong>{field.label}</strong><small>{field.key} · {field.required ? t('review.required') : t('review.optional')}{field.warning ? t('review.warningSuffix') : ''}</small></div>
                  <span className="truncate-cell">{field.sample}</span>
                  <span className="confidence"><i style={{ width: `${field.confidence * 100}%` }} />{Math.round(field.confidence * 100)}%</span>
                  <span className="decision-cell">
                    <Select value={decisions[field.key] ?? 'pending'} onValueChange={(value) => onDecision(field.key, value as FieldReviewDecision)}>
                      <SelectTrigger size="sm" aria-label={t('review.decisionAria', { label: field.label })}><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="pending">{t('review.pendingOption')}</SelectItem>
                        {!field.warning && <SelectItem value="approved">{t('review.approveOption')}</SelectItem>}
                        {field.warning && <SelectItem value="risk_accepted">{t('review.riskAcceptOption')}</SelectItem>}
                        {!field.required && <SelectItem value="excluded">{t('review.excludeOption')}</SelectItem>}
                      </SelectContent>
                    </Select>
                  </span>
                  <Button variant="ghost" size="icon-sm" aria-label={t('review.viewFieldEvidence', { label: field.label })} title={t('review.viewEvidence')} onClick={() => onSelectField(field)}><PanelRightOpen /></Button>
                </div>
              ))}
            </div>
          </section>
        </TabsContent>
        <TabsContent value="samples"><section className="review-sample-section"><div className="section-heading"><div><span className="eyebrow">VALIDATION SAMPLES</span><h2>{t('review.samplesTitle')}</h2><p>{t('review.samplesDescription')}</p></div></div><SampleList items={previewItems} onSelect={onSelectItem} /></section></TabsContent>
      </Tabs>
    </div>
  )
}

function CollectionFlow({ candidate, sourceUrl }: { candidate: CandidateRule; sourceUrl: string }) {
  const { t } = useTranslation('collectorDetail')
  const pagination = candidate.pagination.type === 'page'
    ? t('flow.paginationPage', { parameter: candidate.pagination.parameter, start: candidate.pagination.start, maxPages: candidate.pagination.maxPages })
    : candidate.pagination.type === 'next_link'
    ? t('flow.paginationNextLink', { selector: candidate.pagination.selector, maxPages: candidate.pagination.maxPages })
    : t('flow.paginationNone')
  const singleStage = candidate.mode === 'single'
  const listPublishedAtSelector = !singleStage && 'listPublishedAt' in candidate.gatherSpec.collect.list.fields
    ? candidate.gatherSpec.collect.list.fields.listPublishedAt?.selector
    : undefined
  return <section className="crawl-plan" aria-label={singleStage ? t('flow.singleAria') : t('flow.listDetailAria')}>
    <div className="crawl-plan-heading"><div><span className="eyebrow">DETERMINISTIC CRAWL PLAN</span><h2>{singleStage ? t('flow.singleTitle') : t('flow.listDetailTitle')}</h2><p>{singleStage ? t('flow.singleDescription') : t('flow.listDetailDescription')}</p></div><Badge variant="outline">{singleStage ? '1 STAGE' : '2 STAGES'}</Badge></div>
    <div className={`crawl-stage-grid ${singleStage ? 'single-stage' : ''}`}>
      <article className="crawl-stage-card list-stage">
        <div className="crawl-stage-title"><span>{singleStage ? <FileSearch /> : <ListTree />}</span><div><small>STAGE 01</small><h3>{singleStage ? t('flow.stageDirect') : t('flow.stageList')}</h3></div></div>
        <dl><div><dt>{t('common:evidence.entryUrl')}</dt><dd><code>{sourceUrl}</code></dd></div><div><dt>Item selector</dt><dd><code>{candidate.listSelector}</code></dd></div>{!singleStage && <div><dt>{t('flow.detailLink')}</dt><dd><code>{candidate.detailLinkSelector}</code></dd></div>}{listPublishedAtSelector && <div><dt>{t('flow.listTime')}</dt><dd><code>{listPublishedAtSelector}</code></dd></div>}<div><dt>{t('common:evidence.paginationStrategy')}</dt><dd>{pagination}</dd></div></dl>
        <p>{singleStage ? <ShieldCheck /> : <Route />}{singleStage ? t('flow.singleQualityNote') : t('flow.listSampleNote', { listPages: candidate.discovery.listPagesSampled, detailUrls: candidate.discovery.detailUrlsDiscovered })}</p>
      </article>
      {!singleStage && <><ArrowRight className="crawl-stage-arrow" aria-hidden="true" />
      <article className="crawl-stage-card detail-stage">
        <div className="crawl-stage-title"><span><FileSearch /></span><div><small>STAGE 02</small><h3>{t('flow.detailCollection')}</h3></div></div>
        <dl><div><dt>{t('flow.requestInput')}</dt><dd>{t('flow.requestInputValue')}</dd></div><div><dt>{t('flow.fieldExtraction')}</dt><dd>{t('flow.fieldExtractionValue', { total: candidate.fields.length })}</dd></div><div><dt>{t('flow.qualityFinalization')}</dt><dd>{t('flow.qualityFinalizationValue')}</dd></div><div><dt>{t('flow.validationCoverage')}</dt><dd>{t('flow.validationCoverageValue', { validated: candidate.discovery.detailPagesValidated, total: candidate.discovery.detailPagesValidated })}</dd></div></dl>
        <p><ShieldCheck />{t('flow.detailBoundaryNote')}</p>
      </article></>}
    </div>
    {!singleStage && <div className="detail-url-samples"><span>{t('flow.detailUrlSamples')}</span>{candidate.discovery.detailUrlSamples.map((url) => <code key={url}>{url}</code>)}</div>}
  </section>
}

function isSingleStageSource(sourceUrl: string) {
  return /(?:single|detail-only)/.test(new URL(sourceUrl).pathname)
}

function SampleList({ items, onSelect }: { items: HarvestItem[]; onSelect: (item: HarvestItem) => void }) {
  const { t } = useTranslation('collectorDetail')
  return <div className="sample-list">{items.map((item) => <button type="button" key={item.id} onClick={() => onSelect(item)}><StatusBadge status={item.decision} /><span><strong>{item.title}</strong><small>{t('sample.publishedObserved', { publishedAt: item.publishedAt, observedAt: item.observedAt })}</small></span><ChevronRight /></button>)}</div>
}

function PublishedView({ items, runId, onSelectItem, onOpenRun }: { items: HarvestItem[]; runId: string | null; onSelectItem: (item: HarvestItem) => void; onOpenRun: (id: string) => void }) {
  const { t } = useTranslation('collectorDetail')
  return <div className="workbench-content">{runId ? <section className="content-section recent-results"><div className="section-heading"><div><span className="eyebrow">LATEST RESULTS</span><h2>{t('published.resultsTitle')}</h2><p>{t('published.resultsDescription')}</p></div><Button variant="outline" onClick={() => onOpenRun(runId)}>{t('published.viewFullRun')} <ArrowRight /></Button></div><div className="sample-list item-results">{items.slice(0, 5).map((item) => <div className="sample-result-row" key={item.id}><button type="button" onClick={() => onSelectItem(item)}><StatusBadge status={item.decision} /><span><strong>{item.title}</strong><small>{item.changeType ? `${item.changeType === 'new' ? t('published.changeNew') : item.changeType === 'updated' ? t('published.changeUpdated') : t('published.changeUnchanged')} · ` : ''}{t('sample.publishedObserved', { publishedAt: item.publishedAt, observedAt: item.observedAt })}</small></span><span className="review-count">{t('review.viewEvidence')}</span></button><Button asChild variant="ghost" size="icon-sm" aria-label={t('published.openItemAria', { title: item.title })}><Link to={`/items/${item.id}`}><ArrowRight /></Link></Button></div>)}</div></section> : <Alert><Play /><AlertTitle>{t('published.readyTitle')}</AlertTitle><AlertDescription>{t('published.readyDescription')}</AlertDescription></Alert>}</div>
}

function PublishDialog({ candidate, decisions, pending, disabled, lockReason, onPublish }: { candidate: CandidateRule; decisions: Record<string, FieldReviewDecision>; pending: boolean; disabled: boolean; lockReason?: string | null; onPublish: () => void }) {
  const { t } = useTranslation('collectorDetail')
  const accepted = Object.values(decisions).filter((decision) => decision === 'approved').length
  const riskAccepted = Object.values(decisions).filter((decision) => decision === 'risk_accepted').length
  const excluded = Object.values(decisions).filter((decision) => decision === 'excluded').length
  return <Dialog><DialogTrigger asChild><Button size="lg" disabled={disabled || pending || Boolean(lockReason)} title={lockReason ?? undefined}>{pending ? <><LoaderCircle className="animate-spin" />{t('publish.inProgress')}</> : <><FileCheck2 />{t('publish.trigger')}</>}</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>{t('publish.title')}</DialogTitle><DialogDescription>{t('publish.description')}</DialogDescription></DialogHeader><div className="dialog-proof"><span><strong>{t('publish.reviewer')}</strong>{t('publish.reviewerName')}</span><span><strong>{t('publish.fieldDecisions')}</strong>{t('publish.decisionSummary', { approved: accepted, riskAccepted, excluded })}</span><span><strong>{t('publish.qualityChecks')}</strong>{t('publish.qualitySummary', { passed: candidate.passedChecks, warnings: candidate.warningChecks })}</span></div><DialogFooter><DialogClose asChild><Button variant="ghost">{t('publish.backToReview')}</Button></DialogClose><DialogClose asChild><Button onClick={onPublish} disabled={pending || disabled}>{pending ? t('publish.confirming') : t('publish.confirm')}</Button></DialogClose></DialogFooter></DialogContent></Dialog>
}

function CollectorSkeleton() { return <div className="page-frame"><Skeleton className="h-6 w-24" /><Skeleton className="h-20 w-full" /><Skeleton className="h-14 w-full" /><Skeleton className="h-80 w-full" /></div> }
function NotFound({ message }: { message: string }) {
  const { t } = useTranslation('collectorDetail')
  return <div className="empty-state"><Braces /><h1>{t('notFound.title')}</h1><p>{message}</p><Button asChild><Link to="/collectors">{t('notFound.backToCollectors')}</Link></Button></div>
}
