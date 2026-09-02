import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Bot, Braces, Check, Clock3, FileCheck2, Fingerprint, ListChecks, Route, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { AiRunDetail, ModelInvocation } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function AiRunPage() {
  const { aiRunId = '' } = useParams()
  const query = useQuery({ queryKey: ['ai-run', aiRunId], queryFn: () => api.aiRunDetail(aiRunId) })

  if (query.isLoading) return <div className="page-frame"><Skeleton className="h-80 w-full" /></div>
  const run = query.data
  if (!run) return <div className="empty-state"><h1>AI 任务不存在</h1><Button asChild><Link to="/runs?view=ai">返回 AI 任务</Link></Button></div>

  const source = sourcePresentation(run.sourceUrl, run.collectorName)
  const invocations = run.attempts.flatMap((attempt) => attempt.modelInvocations)
  const active = ['queued', 'running', 'finalizing'].includes(run.status)
  const failed = run.status === 'failed' || run.resultStatus === 'no_candidate'

  return <div className="run-workbench ai-run-workbench">
    <div className="run-page-main">
      <header className="run-page-header ai-run-page-header">
        <div>
          <div className="title-line"><h1 title={source.full}>{source.root}</h1><AiRunState run={run} /></div>
          <div className="run-header-subtitle">
            {source.path && <span className="run-source-path" title={source.full}>{source.path}</span>}
            <span className="run-header-meta">{taskKindLabel(run)} · {formatDateTime(run.createdAt)} 开始</span>
          </div>
        </div>
        <Button asChild variant={run.reviewStatus === 'ready_review' ? 'default' : 'outline'}>
          <Link to={`/collectors/${run.collectorId}`}>
            {run.reviewStatus === 'ready_review' ? '审核候选规则' : '查看采集器'} <ArrowRight />
          </Link>
        </Button>
      </header>

      <Tabs defaultValue="result" className="run-workspace-tabs">
        <div className="run-workspace-nav">
          <TabsList variant="line" aria-label="AI 任务详情视图">
            <TabsTrigger value="result"><Sparkles />结果</TabsTrigger>
            <TabsTrigger value="process"><Route />执行过程</TabsTrigger>
            <TabsTrigger value="models"><Bot />模型调用<span className="tab-count neutral">{invocations.length}</span></TabsTrigger>
            <TabsTrigger value="evidence"><ShieldCheck />证据</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="result" className="run-tab-panel">
          <AiRunSummary run={run} failed={failed} />
          <section className="run-detail-section ai-result-section">
            <header><div><h2>{resultTitle(run)}</h2><p>{resultDescription(run)}</p></div>{run.reviewStatus === 'ready_review' && <Badge variant="outline" className="ai-review-badge">等待人工审核</Badge>}</header>
            <dl className="ai-result-grid">
              <div><dt>样本验证</dt><dd>{run.validationSummary.acceptedSamples} 通过 · {run.validationSummary.rejectedSamples} 拒绝</dd></div>
              <div><dt>质量警告</dt><dd>{run.validationSummary.warningCount}</dd></div>
              <div><dt>执行尝试</dt><dd>{run.attemptCount}</dd></div>
              <div><dt>审核状态</dt><dd>{reviewLabel(run.reviewStatus)}</dd></div>
            </dl>
            {failed && <div className="ai-run-error"><TriangleAlert /><span><strong>未产生可审核的候选规则</strong><small>{run.error?.message ?? '查看执行过程和模型调用，定位失败阶段后重新生成。'}</small></span></div>}
            {active && <div className="ai-run-active"><Clock3 /><span><strong>{phaseLabel(run.phase)}</strong><small>任务在后台执行，离开页面不会中断。</small></span><b>{run.progress}%</b></div>}
          </section>
        </TabsContent>

        <TabsContent value="process" className="run-tab-panel">
          <section className="run-detail-section">
            <header><div><h2>执行尝试</h2><p>失败重试不会覆盖历史，每次尝试独立留痕</p></div></header>
            <div className="ai-attempt-list">
              {run.attempts.map((attempt) => <article key={attempt.id}>
                <span className={`ai-attempt-index ${attempt.status}`}><Check /></span>
                <div><strong>第 {attempt.attemptNo} 次尝试</strong><small>{formatDateTime(attempt.startedAt)} · {durationLabel(attempt.durationMs)}</small></div>
                <Badge variant="outline">{attemptStatusLabel(attempt.status)}</Badge>
                <span className="ai-attempt-models">{attempt.modelInvocations.length} 次模型调用</span>
              </article>)}
              {run.attempts.length === 0 && <div className="card-empty">任务尚未开始执行。</div>}
            </div>
          </section>
        </TabsContent>

        <TabsContent value="models" className="run-tab-panel">
          <section className="run-detail-section ai-model-section">
            <header><div><h2>模型调用</h2><p>只保留调用元数据、用量和响应摘要，不保存原始提示词与响应正文</p></div></header>
            <div className="ai-model-table">
              <div className="ai-model-head"><span>用途</span><span>模型</span><span>状态</span><span>Token</span><span>耗时</span></div>
              {invocations.map((invocation) => <ModelInvocationRow key={invocation.id} invocation={invocation} />)}
              {invocations.length === 0 && <div className="card-empty">暂无模型调用记录。</div>}
            </div>
          </section>
        </TabsContent>

        <TabsContent value="evidence" className="run-tab-panel">
          <section className="run-detail-section run-proof-section" aria-label="AI 任务审计证据">
            <header><div><h2>任务证据</h2><p>执行、模型与候选规则之间的可追溯关系</p></div><Fingerprint /></header>
            <div className="run-proof-grid">
              <article className="verified"><ListChecks /><span><strong>{run.attemptCount} 次执行尝试已记录</strong><small>重试历史不会被覆盖</small></span></article>
              <article className="verified"><Bot /><span><strong>{run.modelSummary.invocationCount} 次模型调用可核对</strong><small>{formatTokens(run.modelSummary.totalTokens)} Token</small></span></article>
              <article className={run.resultStatus === 'candidate_ready' ? 'verified' : 'pending'}><FileCheck2 /><span><strong>{run.resultStatus === 'candidate_ready' ? '候选规则已固定' : '尚无候选规则'}</strong><small>{reviewLabel(run.reviewStatus)}</small></span></article>
              <article className="neutral"><ShieldCheck /><span><strong>敏感正文未入审计记录</strong><small>仅保留摘要与技术元数据</small></span></article>
            </div>
            <details className="run-technical-details">
              <summary><Braces /><span><strong>技术信息</strong><small>用于排障与审计</small></span><ArrowRight /></summary>
              <dl>
                <div><dt>AI Run ID</dt><dd><code>{run.id}</code></dd></div>
                <div><dt>Operation ID</dt><dd><code>{run.operationId}</code></dd></div>
                <div><dt>Collector ID</dt><dd><code>{run.collectorId}</code></dd></div>
                <div><dt>Candidate Digest</dt><dd><code>{run.candidateRuleDigest ?? 'not available'}</code></dd></div>
                <div><dt>Published Rule</dt><dd><code>{run.publishedRuleVersionId ?? 'not published'}</code></dd></div>
                <div><dt>Initiated By</dt><dd><code>{run.initiatedBy}</code></dd></div>
              </dl>
            </details>
          </section>
        </TabsContent>
      </Tabs>
    </div>
  </div>
}

function AiRunSummary({ run, failed }: { run: AiRunDetail; failed: boolean }) {
  return <section aria-label="AI 任务摘要" className={`run-result-summary ${failed ? 'danger' : run.reviewStatus === 'ready_review' ? 'warning' : 'success'}`}>
    <div className="run-result-heading ai-run-summary">
      <div><h2>{failed ? '任务未生成候选规则' : run.reviewStatus === 'ready_review' ? '候选规则等待审核' : resultTitle(run)}</h2><p>{phaseLabel(run.phase)} · {durationLabel(run.durationMs)}</p></div>
      <dl className="run-result-facts ai-run-facts">
        <div><dt>模型调用</dt><dd>{run.modelSummary.invocationCount}</dd></div>
        <div><dt>Token</dt><dd>{formatTokens(run.modelSummary.totalTokens)}</dd></div>
        <div><dt>样本通过</dt><dd>{run.validationSummary.acceptedSamples}</dd></div>
        <div><dt>样本拒绝</dt><dd>{run.validationSummary.rejectedSamples}</dd></div>
        <div><dt>警告</dt><dd>{run.validationSummary.warningCount}</dd></div>
        <div><dt>耗时</dt><dd>{durationLabel(run.durationMs)}</dd></div>
      </dl>
    </div>
  </section>
}

function ModelInvocationRow({ invocation }: { invocation: ModelInvocation }) {
  return <div className="ai-model-row">
    <span><strong>{purposeLabel(invocation.purpose)}</strong><small>Prompt v{invocation.promptVersion}</small></span>
    <span><strong>{invocation.model}</strong><small>{invocation.provider}</small></span>
    <Badge variant="outline" className={invocation.status === 'succeeded' ? 'ai-model-success' : 'ai-model-failed'}>{invocation.status === 'succeeded' ? '成功' : '失败'}</Badge>
    <span><strong>{formatTokens(invocation.totalTokens)}</strong><small>{invocation.promptTokens} 输入 · {invocation.completionTokens} 输出</small></span>
    <span><strong>{durationLabel(invocation.durationMs)}</strong><small>{formatDateTime(invocation.startedAt)}</small></span>
  </div>
}

function AiRunState({ run }: { run: AiRunDetail }) {
  const active = ['queued', 'running', 'finalizing'].includes(run.status)
  const label = run.status === 'failed' ? '失败' : active ? '进行中' : run.reviewStatus === 'ready_review' ? '待审核' : run.reviewStatus === 'published' ? '已发布' : '已完成'
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

function taskKindLabel(run: AiRunDetail) {
  return run.kind === 'rule_repair' ? '规则修复' : run.trigger === 'initial_generation' ? '首次规则生成' : '规则重新生成'
}

function resultTitle(run: AiRunDetail) {
  if (run.resultStatus === 'candidate_ready') return '候选规则已生成'
  if (run.resultStatus === 'no_candidate') return '未生成候选规则'
  return '正在生成候选规则'
}

function resultDescription(run: AiRunDetail) {
  if (run.reviewStatus === 'ready_review') return 'AI 产出仅作为候选，完成字段与样本审核后才能发布。'
  if (run.reviewStatus === 'published') return '候选规则已完成人工审核并发布。'
  if (run.reviewStatus === 'superseded') return '该候选已被更新的生成结果替代。'
  return '执行完成后将在这里显示候选规则与验证结果。'
}

function reviewLabel(status: AiRunDetail['reviewStatus']) {
  return { not_ready: '尚未进入审核', ready_review: '等待人工审核', published: '已审核发布', superseded: '已被新版本替代' }[status]
}

function phaseLabel(phase: AiRunDetail['phase']) {
  return { queued: '等待执行', fetching_list: '读取来源页面', discovering_details: '分析页面结构', fetching_details: '采集验证样本', validating: '验证候选规则', finalizing: '整理任务结果', completed: '执行已完成' }[phase]
}

function attemptStatusLabel(status: AiRunDetail['attempts'][number]['status']) {
  return { queued: '等待', running: '进行中', finalizing: '收尾中', succeeded: '成功', failed: '失败', cancelled: '已取消', timed_out: '已超时' }[status]
}

function purposeLabel(purpose: ModelInvocation['purpose']) {
  return { discover: '页面结构发现', compile: '规则编译', repair: '规则修复' }[purpose]
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(value))
}

function durationLabel(value: number | null) {
  if (value === null) return '执行中'
  if (value < 1000) return `${value}ms`
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`
}

function formatTokens(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}
