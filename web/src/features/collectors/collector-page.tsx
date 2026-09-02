import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  Braces,
  CalendarRange,
  CalendarClock,
  Check,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  FileSearch,
  FileCheck2,
  Globe2,
  Layers3,
  LayoutDashboard,
  ListTree,
  LockKeyhole,
  LoaderCircle,
  PanelRightOpen,
  Pencil,
  Play,
  RefreshCw,
  Route,
  Rocket,
  Save,
  Settings2,
  ShieldCheck,
  WandSparkles,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { api, waitForOperation } from '@/api/client'
import type { AiRun, CandidateField, CandidateRule, CandidateRuleEditInput, CollectionPolicy, CollectionPolicyInput, CollectorDetail, CollectorSchedule, CollectorScheduleInput, FieldReviewDecision, HarvestItem, Operation, UpdateCollectorInput } from '@/api/types'
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
import { Progress } from '@/components/ui/progress'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { collectorDisplayName } from './collector-presentation'

export function CollectorPage() {
  const { collectorId = '' } = useParams()
  const navigate = useNavigate()
  const { setTopbarBackTarget } = useOutletContext<{ setTopbarBackTarget: (target: string | null) => void }>()
  const queryClient = useQueryClient()
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
    if (!operationId || explore.isPending || run.isPending) return
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
  }, [collectorId, explore.isPending, query.data?.activeOperationId, queryClient, run.isPending])

  if (query.isLoading) return <CollectorSkeleton />
  const collector = query.data
  if (!collector) return <NotFound message={query.error?.message ?? 'Collector 不存在'} />

  async function startExploration() {
    setActiveOperation(undefined)
    setOperationError(undefined)
    await explore.mutateAsync()
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
            <div><div className="title-line"><h1>{collectorDisplayName(collector.name)}</h1><StatusBadge status={collector.status} /></div><p className="object-subtitle"><Link className="collection-context-link" to={`/collectors?collection=${encodeURIComponent(collector.collectionId)}`}><Layers3 />{collector.collectionName}</Link><span className="collector-phase">当前阶段：<strong>{collectorPhaseLabel(collector.status, explore.isPending, runPending)}</strong></span></p></div>
          </div>
          <div className="object-actions">
            {collector.status === 'draft' && <Button size="lg" onClick={() => { void startExploration().catch(() => undefined) }} disabled={explore.isPending}>{explore.isPending ? <><LoaderCircle className="animate-spin" />正在探索</> : <><Rocket />生成候选规则</>}</Button>}
            {collector.status === 'exploring' && <Button size="lg" disabled><LoaderCircle className="animate-spin" />探索进行中</Button>}
            {collector.status === 'ready_review' && candidate && (
              <PublishDialog
                candidate={candidate}
                decisions={reviewDecisions}
                pending={publish.isPending}
                disabled={hasPendingDecision}
                onPublish={() => publish.mutate()}
              />
            )}
            {collector.status === 'published' && <Button size="lg" onClick={startRun} disabled={runPending || explore.isPending}>{runPending ? <><LoaderCircle className="animate-spin" />正在运行</> : <><Play />立即运行</>}</Button>}
          </div>
        </header>

        {(explore.isPending || collector.status === 'exploring') && <ExplorationProgress operation={activeOperation} singleStage={isSingleStageSource(collector.sourceUrl)} />}
        {runPending && <RunProgress operation={activeOperation} />}
        {(explore.error || publish.error || savePolicy.error || saveSchedule.error || updateDefinition.error || editCandidate.error || run.error || operationError) && <Alert variant="destructive" className="mt-5"><AlertTitle>操作未完成</AlertTitle><AlertDescription>{explore.error?.message ?? publish.error?.message ?? savePolicy.error?.message ?? saveSchedule.error?.message ?? updateDefinition.error?.message ?? editCandidate.error?.message ?? run.error?.message ?? operationError?.message}</AlertDescription></Alert>}

        <Tabs key={`${collector.id}:${collector.status}`} defaultValue={defaultCollectorTab(collector.status)} className="collector-workspace-tabs">
          <div className="collector-workspace-nav">
            <TabsList variant="line" aria-label="采集器详情视图">
              <TabsTrigger value="overview"><LayoutDashboard />概览</TabsTrigger>
              {candidate && <TabsTrigger value="rule"><ClipboardCheck />{collector.status === 'ready_review' ? '规则审核' : '规则'}{pendingDecisionCount > 0 && <span className="tab-count">{pendingDecisionCount}</span>}</TabsTrigger>}
              <TabsTrigger value="config"><Settings2 />采集配置</TabsTrigger>
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
            <SheetTitle>证据详情</SheetTitle>
            <SheetDescription>查看当前字段、规则或 Item 的采集证据与谱系。</SheetDescription>
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
  if (exploring || status === 'exploring') return '探索'
  if (running) return '运行'
  if (status === 'ready_review') return '审核'
  if (status === 'published') return '已发布'
  return '设计'
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
  const candidate = collector.candidate
  const items = latestRun?.items ?? collector.previewItems
  const runId = latestRun?.id ?? collector.latestRunId
  const acceptedCount = items.filter((item) => item.decision === 'accepted').length
  const rejectedCount = items.filter((item) => item.decision === 'rejected').length
  const pagination = candidate?.pagination.type === 'page'
    ? `最多 ${candidate.pagination.maxPages} 页`
    : candidate?.pagination.type === 'next_link'
      ? `连续翻页，最多 ${candidate.pagination.maxPages} 页`
      : candidate?.mode === 'single' ? '单页直接采集' : '列表 1 页'

  return <div className="collector-overview">
    <section className="collector-overview-summary">
      <div className="overview-state">
        <span className={`overview-state-icon ${collector.status === 'published' ? 'success' : ''}`}>{collector.status === 'published' ? <ShieldCheck /> : <Route />}</span>
        <div><span className="eyebrow">CURRENT STATE</span><h2>{runPending ? '正在执行采集任务' : overviewTitle(collector.status)}</h2><p>{overviewDescription(collector.status, runPending)}</p></div>
        {latestAiRun && <Link className="overview-ai-run" to={`/ai-runs/${latestAiRun.id}`}><WandSparkles /><span><strong>最近 AI 任务</strong><small>{aiRunReviewLabel(latestAiRun)} · {latestAiRun.modelSummary.invocationCount} 次模型调用</small></span><ChevronRight /></Link>}
      </div>
      <dl className="overview-facts">
        <div><dt>入口网址</dt><dd><code className="overview-source-url" title={collector.sourceUrl}>{collector.sourceUrl}</code></dd></div>
        <div><dt>活动规则</dt><dd><strong>{collector.activeRuleVersion ? `${candidate?.fields.length ?? 0} 个字段 · ${candidate?.mode === 'single' ? '直接采集' : '列表到详情'}` : '尚未发布'}</strong><span>{collector.activeRuleVersion ? '已发布并冻结' : '生成候选规则后进入审核'}</span></dd></div>
        <div><dt>运行范围</dt><dd><strong>{pagination}</strong><span>{collector.collectionPolicy ? `回看 ${collector.collectionPolicy.lookbackDays} 天 · 上限 ${collector.collectionPolicy.maxItems} 条` : '使用默认采集策略'}</span></dd></div>
        <div><dt>最近运行</dt><dd><strong>{runId ? `${acceptedCount} 接收 · ${rejectedCount} 拒绝` : '暂无运行'}</strong><span>{runId ? `${latestRun?.duration ?? '已完成'} · watermark ${collector.checkpoint?.watermark ?? '未建立'}` : '发布规则后可立即运行'}</span></dd></div>
      </dl>
    </section>
    {runPending ? <WorkspaceEmpty icon={Play} title="运行正在进行" description="实时阶段和指标显示在页面顶部，完成后最近结果会在这里更新。" /> : collector.status === 'published' ? <PublishedView items={items} runId={runId} onSelectItem={onSelectItem} onOpenRun={onOpenRun} /> : <section className="overview-guidance"><div><span className="eyebrow">NEXT STEP</span><h2>{collector.status === 'ready_review' ? '完成规则审核并发布' : '生成并验证候选规则'}</h2><p>{collector.status === 'ready_review' ? '进入“规则审核”处理待决策字段；技术证据只在需要时从右侧展开。' : '先确认来源定义和采集范围，再启动规则生成。'}</p></div></section>}
  </div>
}

function aiRunReviewLabel(run: AiRun) {
  if (['queued', 'running', 'finalizing'].includes(run.status)) return '进行中'
  if (run.status === 'failed') return '失败'
  return { not_ready: '已完成', ready_review: '待审核', published: '已发布', superseded: '已被替代' }[run.reviewStatus]
}

function overviewTitle(status: CollectorDetail['status']) {
  if (status === 'published') return '采集器已就绪'
  if (status === 'ready_review') return '候选规则等待审核'
  if (status === 'exploring') return '正在生成候选规则'
  return '来源定义已保存'
}

function overviewDescription(status: CollectorDetail['status'], running: boolean) {
  if (running) return '固定活动规则执行中，完成后会更新最近运行和检查点。'
  if (status === 'published') return '活动规则和采集范围已生效，可直接运行或检查最近结果。'
  if (status === 'ready_review') return '候选字段和样本已准备好，需要完成人工决策后发布。'
  if (status === 'exploring') return '系统正在分析入口、分页、详情链接和字段质量。'
  return '确认采集说明、入口网址和运行范围后生成候选规则。'
}

function ValidationWorkspace({ candidate, sourceUrl, published, reviewDecisions }: {
  candidate: CandidateRule
  sourceUrl: string
  published: boolean
  reviewDecisions: Record<string, FieldReviewDecision>
}) {
  const acceptedRisk = Object.values(reviewDecisions).filter((decision) => decision === 'risk_accepted').length
  const excluded = Object.values(reviewDecisions).filter((decision) => decision === 'excluded').length
  const decisionSummary = excluded > 0
    ? `${excluded} 个可选字段已排除，其余字段通过`
    : acceptedRisk > 0
      ? `${acceptedRisk} 个字段已接受风险，其余字段通过`
      : '全部字段通过审核'

  return <div className="validation-workspace">
    <section className="validation-summary">
      <div className="validation-summary-heading"><div><span className="eyebrow">RULE RELEASE</span><h2>{published ? '规则已发布并冻结' : '候选规则已完成验证'}</h2><p>{published ? '运行始终使用这条已审核规则，不会自动变化。' : '完成字段审核后即可发布。'}</p></div><Badge variant="outline">{published ? '已发布' : '候选'}</Badge></div>
      <div className="validation-metrics">
        <span><strong>{candidate.passedChecks}</strong><small>检查通过</small></span>
        <span><strong>{candidate.warningChecks}</strong><small>质量警告</small></span>
        <span><strong>{candidate.discovery.detailPagesValidated}</strong><small>详情样本</small></span>
        <span><strong>{candidate.fields.length}</strong><small>输出字段</small></span>
      </div>
      <div className="validation-release-facts">
        <span><small>采集流程</small><strong>{candidate.mode === 'single' ? '单页直接采集' : '列表发现 → 详情采集'}</strong></span>
        <span><small>审核结论</small><strong>{decisionSummary}</strong></span>
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
  const candidate = collector.candidate
  const ruleState = !candidate
    ? '尚未生成'
    : collector.status === 'published'
      ? '活动规则'
      : '候选待审核'
  const pagination = candidate?.pagination.type === 'next_link'
    ? `next_link · 最多 ${candidate.pagination.maxPages} 页`
    : candidate?.pagination.type === 'page'
      ? `${candidate.pagination.parameter} 参数 · 最多 ${candidate.pagination.maxPages} 页`
      : '不分页'

  return (
    <section className="collector-configuration-grid" aria-label="采集器定义与规则工作区">
      <article className="configuration-card definition-card">
        <div className="configuration-heading">
          <span className="configuration-icon teal"><Settings2 /></span>
          <div><span className="eyebrow">COLLECTOR DEFINITION</span><h2>采集器定义</h2></div>
          <DefinitionDialog
            collector={collector}
            disabled={disabled}
            pending={definitionPending}
            onSave={onSaveDefinition}
            onRegenerate={onRegenerate}
          />
        </div>
        <dl className="configuration-facts">
          <div><dt>所属需求</dt><dd><Link className="configuration-collection-link" to={`/collectors?collection=${encodeURIComponent(collector.collectionId)}`}><Layers3 />{collector.collectionName}</Link></dd></div>
          <div><dt>来源采集说明</dt><dd>{collector.intent}</dd></div>
          <div><dt>入口网址</dt><dd><code>{collector.sourceUrl}</code></dd></div>
        </dl>
        <div className="configuration-footer"><span><LockKeyhole />数据合同</span><code>{collector.collectionVersion}</code></div>
      </article>

      <article className="configuration-card rule-workspace-card">
        <div className="configuration-heading">
          <span className="configuration-icon blue"><Braces /></span>
          <div><span className="eyebrow">RULE WORKSPACE</span><h2>规则工作区</h2></div>
          <Badge variant={collector.status === 'published' ? 'default' : 'outline'}>{ruleState}</Badge>
        </div>
        {candidate ? <>
          <div className="rule-version-row"><span><small>规则状态</small><strong>{collector.status === 'published' ? '已发布并冻结' : '候选等待审核'}</strong></span><span><small>采集模式</small><strong>{candidate.mode === 'single' ? '单阶段' : '列表 → 详情'}</strong></span><span><small>字段</small><strong>{candidate.fields.length} 个</strong></span></div>
          <dl className="rule-facts"><div><dt>列表 selector</dt><dd><code>{candidate.listSelector}</code></dd></div><div><dt>分页</dt><dd>{pagination}</dd></div></dl>
        </> : <div className="rule-empty"><WandSparkles /><div><strong>等待生成候选规则</strong><p>系统将分析入口、分页、详情链接和输出字段，结果进入人工审核。</p></div></div>}
        {collector.status === 'draft' && collector.activeRuleVersion && <p className="rule-rebuild-warning">需求输入已变化，历史版本仍可追溯，但不会继续执行。请重新生成并发布。</p>}
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

  return <Dialog open={open} onOpenChange={handleOpenChange}><DialogTrigger asChild><Button variant="ghost" size="sm" disabled={disabled}><Pencil />编辑</Button></DialogTrigger><DialogContent className="definition-dialog"><DialogHeader><DialogTitle>编辑采集器定义</DialogTitle><DialogDescription>所属需求与数据合同保持不变；采集器名称用于识别来源，来源采集说明和入口网址共同决定候选规则。</DialogDescription></DialogHeader><div className="definition-form"><label><span>采集器名称</span><Input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label><label><span>来源采集说明</span><Textarea rows={5} value={draft.intent} onChange={(event) => setDraft((current) => ({ ...current, intent: event.target.value }))} /></label><label><span>入口网址</span><Input className="selector-input" value={draft.sourceUrl} onChange={(event) => setDraft((current) => ({ ...current, sourceUrl: event.target.value }))} /></label></div>{ruleInputChanged && <Alert><RefreshCw /><AlertTitle>需要生成新规则</AlertTitle><AlertDescription>当前候选将失效，已发布规则保持不可变并留作历史证据。</AlertDescription></Alert>}<DialogFooter><Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>取消</Button><Button variant="outline" onClick={() => void submit(false)} disabled={!changed || !valid || pending}>{action === 'save' ? <LoaderCircle className="animate-spin" /> : <Save />}{ruleInputChanged ? '仅保存定义' : '保存信息'}</Button>{ruleInputChanged && <Button onClick={() => void submit(true)} disabled={!changed || !valid || pending}>{action === 'regenerate' ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}{action === 'regenerate' ? '正在生成' : '保存并重新生成'}</Button>}</DialogFooter></DialogContent></Dialog>
}

function RegenerateRuleDialog({ disabled, pending, hasCandidate, onRegenerate }: { disabled: boolean; pending: boolean; hasCandidate: boolean; onRegenerate: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  async function submit() {
    try {
      await onRegenerate()
      setOpen(false)
    } catch {
      return
    }
  }
  if (!hasCandidate) return <Button onClick={() => void submit()} disabled={disabled}>{pending ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}{pending ? '正在生成' : '生成候选规则'}</Button>
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button variant="outline" disabled={disabled}><RefreshCw />重新生成</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>重新生成候选规则？</DialogTitle><DialogDescription>系统会重新访问 Source 并替换当前候选。已发布规则和历史 Run 不会改变；新候选必须重新审核和发布。</DialogDescription></DialogHeader><DialogFooter><Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>取消</Button><Button onClick={() => void submit()} disabled={pending}>{pending ? <LoaderCircle className="animate-spin" /> : <WandSparkles />}{pending ? '正在生成' : '确认重新生成'}</Button></DialogFooter></DialogContent></Dialog>
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

const listFieldLabels: Record<string, string> = {
  title: '列表标题',
  publishTime: '发布时间',
  listTitle: '列表标题',
  listPublishedAt: '列表发布时间',
  detailUrl: '详情 URL',
}

const systemManagedFieldKeys = new Set(['source', 'crawlTime', 'observedAt'])

function fieldDrafts(rules: Record<string, GatherFieldRule>, labels: Record<string, string>): RuleFieldDraft[] {
  return Object.entries(rules).map(([key, rule]) => ({
    key,
    label: labels[key] ?? key,
    selector: rule.selector,
  }))
}

function ruleEditorDraft(candidate: CandidateRule): RuleEditorDraft {
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
      ? fieldDrafts(candidate.gatherSpec.collect.list.fields, listFieldLabels)
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
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<RuleEditorDraft>(() => ruleEditorDraft(candidate))
  const input = ruleEditInput(draft, candidate.mode)
  const original = ruleEditInput(ruleEditorDraft(candidate), candidate.mode)
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
    if (next) setDraft(ruleEditorDraft(candidate))
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
    <DialogTrigger asChild><Button disabled={disabled}><Pencil />编辑规则</Button></DialogTrigger>
    <DialogContent className="rule-editor-dialog">
      <DialogHeader className="rule-editor-header">
        <div><DialogTitle>编辑规则</DialogTitle><DialogDescription>修改 selector 与分页，保存后生成新的待审核候选。</DialogDescription></div>
      </DialogHeader>
      <Tabs defaultValue="edit" className="rule-editor-tabs">
        <div className="rule-editor-tabbar"><TabsList variant="line" aria-label="规则配置视图"><TabsTrigger value="edit"><Pencil />规则编辑</TabsTrigger><TabsTrigger value="contract"><Braces />JSON</TabsTrigger></TabsList></div>
        <TabsContent value="edit" className="rule-editor-edit-panel">
      <div className="rule-editor-scroll">
          <section className="rule-stage-section">
            <div className="rule-stage-marker"><span>1</span></div>
            <div className="rule-stage-content">
              <header><h3>{candidate.mode === 'single' ? '页面提取' : '列表发现'}</h3></header>
              <label className="rule-primary-selector"><span>Item selector</span><Input aria-label="列表 Item selector" className="selector-input" value={draft.listSelector} onChange={(event) => setDraft((current) => ({ ...current, listSelector: event.target.value }))} /></label>
              {candidate.mode === 'list_detail' && <div className="rule-subsection"><div className="rule-subsection-heading"><h4>列表字段</h4></div><div className="rule-field-editor-list">{draft.listFields.map((field, index) => systemManagedFieldKeys.has(field.key) ? null : <RuleFieldEditor key={field.key} field={field} onChange={(selector) => setField('listFields', index, selector)} />)}</div></div>}
              {candidate.mode === 'list_detail' && <div className="rule-subsection pagination-workbench"><div className="rule-subsection-heading"><h4>分页</h4></div><div className="pagination-editor"><label><span>方式</span><Select value={draft.paginationType} onValueChange={(value) => setDraft((current) => ({ ...current, paginationType: value as RuleEditorDraft['paginationType'] }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="next_link">下一页链接</SelectItem><SelectItem value="page">页码参数</SelectItem></SelectContent></Select></label>{draft.paginationType === 'next_link' ? <label className="pagination-selector"><span>下一页 selector</span><Input aria-label="下一页 selector" className="selector-input" value={draft.paginationSelector} onChange={(event) => setDraft((current) => ({ ...current, paginationSelector: event.target.value }))} /></label> : <><label><span>参数名</span><Input value={draft.pageParameter} onChange={(event) => setDraft((current) => ({ ...current, pageParameter: event.target.value }))} /></label><label><span>起始页</span><Input type="number" min={0} value={draft.pageStart} onChange={(event) => setDraft((current) => ({ ...current, pageStart: Number(event.target.value) }))} /></label><label><span>步长</span><Input type="number" min={1} value={draft.pageStep} onChange={(event) => setDraft((current) => ({ ...current, pageStep: Number(event.target.value) }))} /></label></>}<label><span>最多页数</span><Input type="number" min={1} max={100000} value={draft.maxPages} onChange={(event) => setDraft((current) => ({ ...current, maxPages: Number(event.target.value) }))} /></label>{draft.paginationType === 'page' && <label className="pagination-check"><Checkbox checked={draft.stopWhenNoItems} onCheckedChange={(checked) => setDraft((current) => ({ ...current, stopWhenNoItems: checked === true }))} /><span>空页时停止</span></label>}</div></div>}
              {candidate.mode === 'single' && <div className="rule-subsection"><div className="rule-subsection-heading"><h4>输出字段</h4></div><div className="rule-field-editor-list">{draft.detailFields.map((field, index) => <RuleFieldEditor key={field.key} field={field} onChange={(selector) => setField('detailFields', index, selector)} />)}</div></div>}
            </div>
          </section>
          {candidate.mode === 'list_detail' && <>
            <div className="rule-stage-bridge"><code>detailUrl</code><ArrowRight /><span>详情采集</span></div>
            <section className="rule-stage-section detail-rule-stage">
              <div className="rule-stage-marker"><span>2</span></div>
              <div className="rule-stage-content">
                <header><h3>详情采集</h3></header>
                <div className="rule-subsection"><div className="rule-subsection-heading"><h4>输出字段</h4></div><div className="rule-field-editor-list">{draft.detailFields.map((field, index) => <RuleFieldEditor key={field.key} field={field} onChange={(selector) => setField('detailFields', index, selector)} />)}</div></div>
              </div>
            </section>
          </>}
      </div>
      <div className="rule-editor-footer"><strong>{changed ? `${changeCount} 处修改` : '暂无修改'}</strong><DialogFooter><Button variant="ghost" onClick={() => setDialogOpen(false)} disabled={pending}>取消</Button><Button onClick={() => void submit()} disabled={!changed || !valid || pending}>{pending ? <LoaderCircle className="animate-spin" /> : <Save />}{pending ? '保存并验证中' : '保存为新候选'}</Button></DialogFooter></div>
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

function scheduleLabel(cron: string) {
  const parts = cron.trim().split(/\s+/)
  if (cron === '0 */6 * * *') return '每 6 小时'
  if (parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])) {
    const time = `${parts[1].padStart(2, '0')}:${parts[0].padStart(2, '0')}`
    if (parts[4] === '*') return `每天 ${time}`
    if (parts[4] === '1-5') return `工作日 ${time}`
    const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][Number(parts[4])]
    if (weekday) return `${weekday} ${time}`
  }
  return `自定义 Cron · ${cron}`
}

function scheduleTime(value: string | null) {
  if (!value) return '启用后计算'
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value))
}

function SchedulePanel({ schedule, disabled, pending, onSave }: {
  schedule: CollectorSchedule
  disabled: boolean
  pending: boolean
  onSave: (input: CollectorScheduleInput) => void
}) {
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

  return <section className="schedule-panel" aria-label="定时运行计划">
    <div className="collection-policy-heading">
      <span className="policy-icon schedule-icon"><CalendarClock /></span>
      <div><span className="eyebrow">RUN SCHEDULE</span><h2>定时运行</h2><p>控制采集器何时自动执行；已有运行尚未结束时跳过本次，不并发重复采集。</p></div>
      <Dialog open={open} onOpenChange={setDialogOpen}><DialogTrigger asChild><Button variant="outline" size="sm" disabled={disabled}><Pencil />配置计划</Button></DialogTrigger><DialogContent className="schedule-dialog"><DialogHeader><DialogTitle>配置定时运行</DialogTitle><DialogDescription>使用常用频率即可，Cron 仅在自定义模式下需要填写。</DialogDescription></DialogHeader>
        <div className="schedule-controls">
          <label className="schedule-enabled"><Checkbox checked={draft.enabled} onCheckedChange={(checked) => setDraft((currentDraft) => ({ ...currentDraft, enabled: checked === true }))} /><span><strong>启用自动运行</strong><small>关闭后仍可使用“立即运行”</small></span></label>
          <label><span>执行频率</span><Select value={draft.preset} onValueChange={(value) => setDraft((currentDraft) => ({ ...currentDraft, preset: value as SchedulePreset }))} disabled={!draft.enabled}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="every_6h">每 6 小时</SelectItem><SelectItem value="daily">每天</SelectItem><SelectItem value="weekdays">工作日</SelectItem><SelectItem value="weekly">每周</SelectItem><SelectItem value="custom">自定义 Cron</SelectItem></SelectContent></Select></label>
          {draft.preset !== 'every_6h' && draft.preset !== 'custom' && <label><span>执行时间</span><Input type="time" value={draft.time} onChange={(event) => setDraft((currentDraft) => ({ ...currentDraft, time: event.target.value }))} disabled={!draft.enabled} /></label>}
          {draft.preset === 'weekly' && <label><span>每周</span><Select value={draft.weekday} onValueChange={(value) => setDraft((currentDraft) => ({ ...currentDraft, weekday: value }))} disabled={!draft.enabled}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="1">周一</SelectItem><SelectItem value="2">周二</SelectItem><SelectItem value="3">周三</SelectItem><SelectItem value="4">周四</SelectItem><SelectItem value="5">周五</SelectItem><SelectItem value="6">周六</SelectItem><SelectItem value="0">周日</SelectItem></SelectContent></Select></label>}
          {draft.preset === 'custom' && <label className="schedule-custom-cron"><span>Cron 表达式</span><Input className="selector-input" value={draft.customCron} onChange={(event) => setDraft((currentDraft) => ({ ...currentDraft, customCron: event.target.value }))} placeholder="0 8 * * *" disabled={!draft.enabled} /><small>5 段格式：分钟 小时 日期 月份 星期</small></label>}
          <div className="schedule-guardrails"><span><small>时区</small><strong>中国标准时间</strong></span><span><small>运行冲突</small><strong>跳过本次</strong></span><span><small>实际 Cron</small><code>{cronExpression}</code></span></div>
        </div>
        <DialogFooter><DialogClose asChild><Button variant="ghost">取消</Button></DialogClose><Button onClick={submit} disabled={disabled || !changed || !valid}>{pending ? <LoaderCircle className="animate-spin" /> : <Save />}{pending ? '保存中' : '保存计划'}</Button></DialogFooter>
      </DialogContent></Dialog>
    </div>
    <div className="policy-summary-grid schedule-summary-grid">
      <span><small>状态</small><strong>{schedule.enabled ? '自动运行已启用' : '仅手动运行'}</strong></span>
      <span><small>频率</small><strong>{schedule.enabled ? scheduleLabel(schedule.cronExpression) : '未设置'}</strong></span>
      <span><small>下次运行</small><strong>{schedule.enabled ? scheduleTime(schedule.nextRunAt) : '—'}</strong></span>
      <span><small>运行冲突</small><strong>已有运行时跳过</strong></span>
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
    <section className="collection-policy-panel" aria-label="采集范围与增量策略">
      <div className="collection-policy-heading">
        <span className="policy-icon"><CalendarRange /></span>
        <div><span className="eyebrow">COLLECTION POLICY</span><h2>采集范围与增量</h2><p>首次按时间窗口回溯；后续从成功检查点回看，分页规则仍由已发布规则固定。</p></div>
        <div className="policy-heading-actions"><Dialog open={open} onOpenChange={setDialogOpen}><DialogTrigger asChild><Button variant="outline" size="sm" disabled={disabled}><Pencil />编辑策略</Button></DialogTrigger><DialogContent className="policy-dialog"><DialogHeader><DialogTitle>编辑采集范围与增量</DialogTitle><DialogDescription>保存后立即应用于后续运行，历史运行保持不变。</DialogDescription></DialogHeader><div className="policy-controls">
          <label><span>首次窗口</span><Select value={String(draft.initialWindowDays)} onValueChange={(value) => setNumber('initialWindowDays', value)} disabled={disabled}><SelectTrigger size="sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="7">最近 7 天</SelectItem><SelectItem value="30">最近 30 天</SelectItem><SelectItem value="90">最近 90 天</SelectItem><SelectItem value="180">最近 180 天</SelectItem></SelectContent></Select></label>
          <label><span>增量回看</span><div className="number-control"><Input type="number" min={0} max={90} value={draft.lookbackDays} onChange={(event) => setNumber('lookbackDays', event.target.value)} disabled={disabled} /><small>天</small></div></label>
          <label><span>连续旧页停止</span><div className="number-control"><Input type="number" min={1} max={10} value={draft.consecutiveOlderPages} onChange={(event) => setNumber('consecutiveOlderPages', event.target.value)} disabled={disabled} /><small>页</small></div></label>
          <label><span>分页上限</span><div className="number-control"><Input type="number" min={1} max={1000} value={draft.maxPages} onChange={(event) => setNumber('maxPages', event.target.value)} disabled={disabled} /><small>页</small></div></label>
          <label><span>明细上限</span><div className="number-control"><Input type="number" min={1} max={100000} value={draft.maxItems} onChange={(event) => setNumber('maxItems', event.target.value)} disabled={disabled} /><small>条</small></div></label>
        </div><DialogFooter><DialogClose asChild><Button variant="ghost">取消</Button></DialogClose><Button onClick={submit} disabled={disabled || !changed}>{pending ? <LoaderCircle className="animate-spin" /> : <Save />}{pending ? '保存中' : '保存策略'}</Button></DialogFooter></DialogContent></Dialog></div>
      </div>
      <div className="policy-summary-grid">
        <span><small>首次窗口</small><strong>最近 {initial.initialWindowDays} 天</strong></span>
        <span><small>增量回看</small><strong>{initial.lookbackDays} 天</strong></span>
        <span><small>停止条件</small><strong>连续 {initial.consecutiveOlderPages} 个旧页</strong></span>
        <span><small>运行上限</small><strong>{initial.maxPages} 页 · {initial.maxItems} 条</strong></span>
      </div>
    </section>
  )
}

function ExplorationProgress({ operation, singleStage }: { operation?: Operation; singleStage: boolean }) {
  const phase = operation?.phase ?? 'queued'
  const copy = {
    queued: ['探索任务已排队', '正在分配受限的探索 Worker。'],
    fetching_list: [singleStage ? '正在获取采集入口' : '正在获取列表入口', '传输协议与主机边界已确认，正在读取 Source 响应。'],
    discovering_details: ['正在识别分页与详情链接', '正在生成列表 selector、分页策略和 detail URL 规则。'],
    fetching_details: ['正在采集详情样本', '每个 detail URL 都在重新执行网络边界和请求预算检查。'],
    validating: [singleStage ? '正在验证直接提取字段' : '正在验证详情字段', '候选字段正在通过类型、身份与质量门检查。'],
    finalizing: ['正在冻结候选规则', 'GatherSpec、证据摘要与质量警告正在终结。'],
    completed: ['候选规则已就绪', '字段预览与采集证据已进入审核区。'],
  } as const
  const [title, detail] = copy[phase]
  const phases = singleStage
    ? ['queued', 'fetching_list', 'validating', 'completed']
    : ['queued', 'fetching_list', 'discovering_details', 'fetching_details', 'validating', 'completed']
  const labels = singleStage
    ? ['排队', '获取入口', '字段验证', '候选终结']
    : ['排队', '列表分页', '详情发现', '详情采集', '字段验证', '候选终结']
  const currentIndex = Math.max(0, phases.indexOf(phase))
  return <div className="workbench-content progress-view" aria-live="polite"><span className="pulse-icon"><LoaderCircle className="animate-spin" /></span><div><span className="eyebrow">CRAWL4AI · {phase.toUpperCase()}</span><h2>{title}</h2><p>{detail}</p></div><Progress value={operation?.progress ?? 6} /><div className="progress-steps">{labels.map((label, index) => <span className={index === currentIndex ? 'active' : index < currentIndex ? 'done' : ''} key={label}>{index <= currentIndex ? <Check /> : <LoaderCircle />}{label}</span>)}</div></div>
}

function RunProgress({ operation }: { operation?: Operation }) {
  const phase = operation?.phase ?? 'queued'
  const copy = {
    queued: ['运行已排队', '正在获取执行租约并固定活动规则。'],
    fetching_list: ['正在执行已发布规则', 'Crawlee 正在获取入口与分页响应。'],
    discovering_details: ['正在发现详情 URL', '详情链接正在规范化、去重并接受同源检查。'],
    fetching_details: ['正在抓取详情页', '详情请求正在受预算、重试与 redirect 策略约束。'],
    validating: ['正在执行质量检查', '提取结果正在通过类型、身份与必填门。'],
    finalizing: ['正在终结质量决定', 'accepted set 与 rejected set 正在冻结，尚未产生交付副作用。'],
    completed: ['运行终态已写入', '结果、证据与恢复信息已经可查询。'],
  } as const
  const [title, detail] = copy[phase]
  const metrics = operation?.metrics
  return <div className="workbench-content progress-view" aria-live="polite"><span className="pulse-icon blue"><Play /></span><div><span className="eyebrow">CRAWLEE · {phase.toUpperCase()}</span><h2>{title}</h2><p>{detail}</p></div><Progress value={operation?.progress ?? 6} /><div className="metric-strip"><span><strong>{metrics?.listPagesFetched ?? 0}</strong> 入口页</span><span><strong>{metrics?.detailUrlsDiscovered ?? 0}</strong> 详情链接</span><span><strong>{metrics?.detailPagesFetched ?? 0}</strong> 详情页</span><span><strong>{metrics?.warningCount ?? 0}</strong> 质量警告</span></div></div>
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
  const decided = candidate.fields.filter((field) => (decisions[field.key] ?? 'pending') !== 'pending').length
  const unresolvedWarnings = candidate.fields.filter((field) => field.warning && (decisions[field.key] ?? 'pending') === 'pending')
  const pending = candidate.fields.length - decided
  return (
    <div className="review-workspace">
      {unresolvedWarnings.length > 0 ? <section className="review-blocker"><span className="review-blocker-icon"><CircleAlert /></span><div><span className="eyebrow">BLOCKING REVIEW</span><h2>{unresolvedWarnings.length} 项问题阻止发布</h2><p><strong>{unresolvedWarnings.map((field) => field.label).join('、')}</strong>：{unresolvedWarnings[0].warning}</p></div><Button variant="outline" onClick={() => onSelectField(unresolvedWarnings[0])}><PanelRightOpen />查看证据</Button></section> : <section className="review-blocker is-clear"><span className="review-blocker-icon"><ShieldCheck /></span><div><span className="eyebrow">READY TO PUBLISH</span><h2>字段风险已处置</h2><p>所有质量警告均已接受风险或排除字段，可以发布候选规则。</p></div></section>}
      <div className="review-summary-strip" aria-label="审核摘要">
        <span><strong>{candidate.fields.length}</strong><small>字段</small></span>
        <span><strong>{decided}</strong><small>已决策</small></span>
        <span className={pending > 0 ? 'attention' : ''}><strong>{pending}</strong><small>待决策</small></span>
        <span><strong>{candidate.discovery.detailPagesValidated}/{candidate.discovery.detailPagesValidated}</strong><small>验证样本</small></span>
      </div>
      <Tabs defaultValue="fields" className="review-content-tabs">
        <TabsList variant="line"><TabsTrigger value="fields">字段审核</TabsTrigger><TabsTrigger value="samples">样本数据 <span className="tab-count neutral">{previewItems.length}</span></TabsTrigger></TabsList>
        <TabsContent value="fields">
          <section className="review-field-section">
            <div className="section-heading"><div><span className="eyebrow">CANDIDATE FIELDS</span><h2>逐字段确认输出合同</h2><p>Selector、DOM 片段与来源证据按需查看，不占用主审核表格。</p></div><span className="review-count">已决策 {decided}/{candidate.fields.length}</span></div>
            <div className="field-table review-field-table">
              <div className="field-table-head"><span>字段</span><span>提取样本</span><span>置信度</span><span>审核决定</span><span aria-hidden="true" /></div>
              {candidate.fields.map((field) => (
                <div className={`field-row ${selectedField?.key === field.key ? 'is-selected' : ''}`} key={field.key}>
                  <div className="field-name-button"><strong>{field.label}</strong><small>{field.key} · {field.required ? '必填' : '可选'}{field.warning ? ' · 有警告' : ''}</small></div>
                  <span className="truncate-cell">{field.sample}</span>
                  <span className="confidence"><i style={{ width: `${field.confidence * 100}%` }} />{Math.round(field.confidence * 100)}%</span>
                  <span className="decision-cell">
                    <Select value={decisions[field.key] ?? 'pending'} onValueChange={(value) => onDecision(field.key, value as FieldReviewDecision)}>
                      <SelectTrigger size="sm" aria-label={`${field.label}审核决定`}><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="pending">待决策</SelectItem>
                        {!field.warning && <SelectItem value="approved">确认纳入</SelectItem>}
                        {field.warning && <SelectItem value="risk_accepted">接受风险</SelectItem>}
                        {!field.required && <SelectItem value="excluded">排除字段</SelectItem>}
                      </SelectContent>
                    </Select>
                  </span>
                  <Button variant="ghost" size="icon-sm" aria-label={`查看${field.label}证据`} title="查看证据" onClick={() => onSelectField(field)}><PanelRightOpen /></Button>
                </div>
              ))}
            </div>
          </section>
        </TabsContent>
        <TabsContent value="samples"><section className="review-sample-section"><div className="section-heading"><div><span className="eyebrow">VALIDATION SAMPLES</span><h2>样本数据与质量结论</h2><p>选择一条样本查看 Item 谱系、详情 URL 和采集版本。</p></div></div><SampleList items={previewItems} onSelect={onSelectItem} /></section></TabsContent>
      </Tabs>
    </div>
  )
}

function CollectionFlow({ candidate, sourceUrl }: { candidate: CandidateRule; sourceUrl: string }) {
  const pagination = candidate.pagination.type === 'page'
    ? `page · ${candidate.pagination.parameter}=${candidate.pagination.start}… · 最多 ${candidate.pagination.maxPages} 页`
    : candidate.pagination.type === 'next_link'
    ? `next_link · ${candidate.pagination.selector} · 最多 ${candidate.pagination.maxPages} 页`
    : '不分页'
  const singleStage = candidate.mode === 'single'
  const listPublishedAtSelector = !singleStage && 'listPublishedAt' in candidate.gatherSpec.collect.list.fields
    ? candidate.gatherSpec.collect.list.fields.listPublishedAt?.selector
    : undefined
  return <section className="crawl-plan" aria-label={singleStage ? '单阶段采集流程' : '两阶段采集流程'}>
    <div className="crawl-plan-heading"><div><span className="eyebrow">DETERMINISTIC CRAWL PLAN</span><h2>{singleStage ? '入口获取与字段提取在同一个阶段完成' : '列表发现与详情采集在同一个 Run 内完成'}</h2><p>{singleStage ? '单页 Source 直接提取字段，仍受固定 RuleVersion、请求预算与质量终结约束。' : '两阶段共享固定 RuleVersion、请求预算与最终质量终结，不拆成两个独立任务。'}</p></div><Badge variant="outline">{singleStage ? '1 STAGE' : '2 STAGES'}</Badge></div>
    <div className={`crawl-stage-grid ${singleStage ? 'single-stage' : ''}`}>
      <article className="crawl-stage-card list-stage">
        <div className="crawl-stage-title"><span>{singleStage ? <FileSearch /> : <ListTree />}</span><div><small>STAGE 01</small><h3>{singleStage ? '直接采集' : '列表发现'}</h3></div></div>
        <dl><div><dt>采集入口</dt><dd><code>{sourceUrl}</code></dd></div><div><dt>Item selector</dt><dd><code>{candidate.listSelector}</code></dd></div>{!singleStage && <div><dt>详情链接</dt><dd><code>{candidate.detailLinkSelector}</code></dd></div>}{listPublishedAtSelector && <div><dt>列表时间</dt><dd><code>{listPublishedAtSelector}</code></dd></div>}<div><dt>分页策略</dt><dd>{pagination}</dd></div></dl>
        <p>{singleStage ? <ShieldCheck /> : <Route />}{singleStage ? '单页字段直接进入类型、身份与质量门检查。' : `样本遍历 ${candidate.discovery.listPagesSampled} 个列表页，发现 ${candidate.discovery.detailUrlsDiscovered} 条详情链接。`}</p>
      </article>
      {!singleStage && <><ArrowRight className="crawl-stage-arrow" aria-hidden="true" />
      <article className="crawl-stage-card detail-stage">
        <div className="crawl-stage-title"><span><FileSearch /></span><div><small>STAGE 02</small><h3>详情采集</h3></div></div>
        <dl><div><dt>请求输入</dt><dd>Stage 01 规范化后的 detail URL</dd></div><div><dt>字段提取</dt><dd>{candidate.fields.length} 个字段 · detail 优先合并</dd></div><div><dt>质量终结</dt><dd>类型转换 → identity → required → accepted/rejected</dd></div><div><dt>验证覆盖</dt><dd>{candidate.discovery.detailPagesValidated}/{candidate.discovery.detailPagesValidated} 个详情样本通过</dd></div></dl>
        <p><ShieldCheck />每个详情 URL 重新执行 allowedHosts、redirect 与请求预算检查。</p>
      </article></>}
    </div>
    {!singleStage && <div className="detail-url-samples"><span>发现的详情 URL 样本</span>{candidate.discovery.detailUrlSamples.map((url) => <code key={url}>{url}</code>)}</div>}
  </section>
}

function isSingleStageSource(sourceUrl: string) {
  return /(?:single|detail-only)/.test(new URL(sourceUrl).pathname)
}

function SampleList({ items, onSelect }: { items: HarvestItem[]; onSelect: (item: HarvestItem) => void }) {
  return <div className="sample-list">{items.map((item) => <button type="button" key={item.id} onClick={() => onSelect(item)}><StatusBadge status={item.decision} /><span><strong>{item.title}</strong><small>发布时间 {item.publishedAt} · 采集时间 {item.observedAt}</small></span><ChevronRight /></button>)}</div>
}

function PublishedView({ items, runId, onSelectItem, onOpenRun }: { items: HarvestItem[]; runId: string | null; onSelectItem: (item: HarvestItem) => void; onOpenRun: (id: string) => void }) {
  return <div className="workbench-content">{runId ? <section className="content-section recent-results"><div className="section-heading"><div><span className="eyebrow">LATEST RESULTS</span><h2>最近采集结果</h2><p>仅展示最近 5 条，完整执行证据和质量统计进入 Run 详情。</p></div><Button variant="outline" onClick={() => onOpenRun(runId)}>查看完整 Run <ArrowRight /></Button></div><div className="sample-list item-results">{items.slice(0, 5).map((item) => <div className="sample-result-row" key={item.id}><button type="button" onClick={() => onSelectItem(item)}><StatusBadge status={item.decision} /><span><strong>{item.title}</strong><small>{item.changeType ? `${item.changeType === 'new' ? '新增' : item.changeType === 'updated' ? '更新' : '未变化'} · ` : ''}发布时间 {item.publishedAt} · 采集时间 {item.observedAt}</small></span><span className="review-count">查看证据</span></button><Button asChild variant="ghost" size="icon-sm" aria-label={`打开 ${item.title}`}><Link to={`/items/${item.id}`}><ArrowRight /></Link></Button></div>)}</div></section> : <Alert><Play /><AlertTitle>规则已就绪</AlertTitle><AlertDescription>点击“立即运行”执行一次固定版本的采集并查看结果。</AlertDescription></Alert>}</div>
}

function PublishDialog({ candidate, decisions, pending, disabled, onPublish }: { candidate: CandidateRule; decisions: Record<string, FieldReviewDecision>; pending: boolean; disabled: boolean; onPublish: () => void }) {
  const accepted = Object.values(decisions).filter((decision) => decision === 'approved').length
  const riskAccepted = Object.values(decisions).filter((decision) => decision === 'risk_accepted').length
  const excluded = Object.values(decisions).filter((decision) => decision === 'excluded').length
  return <Dialog><DialogTrigger asChild><Button size="lg" disabled={disabled || pending}>{pending ? <><LoaderCircle className="animate-spin" />正在发布</> : <><FileCheck2 />审核并发布</>}</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>发布规则？</DialogTitle><DialogDescription>发布后规则内容不可变。请确认字段决定与质量检查结果。</DialogDescription></DialogHeader><div className="dialog-proof"><span><strong>审核人</strong>林然</span><span><strong>字段决定</strong>{accepted} 确认 · {riskAccepted} 接受风险 · {excluded} 排除</span><span><strong>质量检查</strong>{candidate.passedChecks} 通过 · {candidate.warningChecks} 警告已处置</span></div><DialogFooter><DialogClose asChild><Button variant="ghost">返回检查</Button></DialogClose><DialogClose asChild><Button onClick={onPublish} disabled={pending || disabled}>{pending ? '正在发布…' : '确认发布'}</Button></DialogClose></DialogFooter></DialogContent></Dialog>
}

function CollectorSkeleton() { return <div className="page-frame"><Skeleton className="h-6 w-24" /><Skeleton className="h-20 w-full" /><Skeleton className="h-14 w-full" /><Skeleton className="h-80 w-full" /></div> }
function NotFound({ message }: { message: string }) { return <div className="empty-state"><Braces /><h1>无法打开对象</h1><p>{message}</p><Button asChild><Link to="/collectors">返回采集器</Link></Button></div> }
