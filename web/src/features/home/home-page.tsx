import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, CircleAlert, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import type { CollectorDetail, HarvestItem, Run } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { collectorDisplayName } from '@/features/collectors/collector-presentation'

type AttentionItem = {
  collector: CollectorDetail
  run?: Run
  label: string
  detail: string
  target: string
  tone: 'danger' | 'warning' | 'info'
  rank: number
}

type TrendGranularity = 'day' | 'week' | 'month'

type DashboardRange = {
  start: Date
  end: Date
}

type TrendBucket = {
  key: string
  label: string
  title: string
  volume: number
  accepted: number
  rejected: number
  runs: number
  successful: number
  partial: number
  failed: number
  tone: 'succeeded' | 'partially_succeeded' | 'failed' | 'empty'
}

const trendGranularities: { value: TrendGranularity; label: string; range: string }[] = [
  { value: 'day', label: '按日', range: '最近 14 天' },
  { value: 'week', label: '按周', range: '最近 12 周' },
  { value: 'month', label: '按月', range: '最近 12 个月' },
]

function attentionFor(collector: CollectorDetail, latestRun?: Run): AttentionItem | null {
  if (latestRun && ['failed', 'cancelled', 'timed_out'].includes(latestRun.status)) {
    return { collector, run: latestRun, label: '修复运行失败', detail: latestRun.summary, target: `/runs/${latestRun.id}`, tone: 'danger', rank: 0 }
  }
  if (latestRun?.status === 'partially_succeeded') {
    return { collector, run: latestRun, label: '处理部分成功运行', detail: partialRunDetail(latestRun), target: `/runs/${latestRun.id}`, tone: 'danger', rank: 1 }
  }
  if (collector.status === 'ready_review') {
    return { collector, label: '完成规则审核', detail: '候选规则等待审核与发布', target: `/collectors/${collector.id}`, tone: 'warning', rank: 2 }
  }
  if (collector.status === 'draft') {
    return { collector, label: '生成候选规则', detail: '尚未完成来源探索', target: `/collectors/${collector.id}`, tone: 'info', rank: 3 }
  }
  if (collector.status === 'exploring') {
    return { collector, label: '查看探索进度', detail: '候选规则正在生成', target: `/collectors/${collector.id}`, tone: 'info', rank: 4 }
  }
  if (collector.status === 'published' && !latestRun) {
    return { collector, label: '执行首次运行', detail: '规则已发布但尚未验证', target: `/collectors/${collector.id}`, tone: 'info', rank: 5 }
  }
  if (latestRun && latestRun.rejectedCount > 0) {
    return { collector, run: latestRun, label: '检查拒绝数据', detail: `${latestRun.rejectedCount} 条数据未通过质量门`, target: `/runs/${latestRun.id}`, tone: 'warning', rank: 6 }
  }
  return null
}

export function HomePage() {
  const [granularity, setGranularity] = useState<TrendGranularity>('day')
  const collectorsQuery = useQuery({ queryKey: ['collectors'], queryFn: api.collectors })
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  const itemsQuery = useQuery({ queryKey: ['items'], queryFn: api.items })
  const collectors = useMemo(() => collectorsQuery.data ?? [], [collectorsQuery.data])
  const runs = useMemo(() => runsQuery.data ?? [], [runsQuery.data])
  const items = useMemo(() => latestEntities(itemsQuery.data ?? []), [itemsQuery.data])
  const runById = useMemo(() => new Map(runs.map((run) => [run.id, run])), [runs])
  const attentionItems = useMemo(() => collectors
    .map((collector) => attentionFor(collector, collector.latestRunId ? runById.get(collector.latestRunId) : undefined))
    .filter((item): item is AttentionItem => item !== null)
    .sort((left, right) => left.rank - right.rank), [collectors, runById])

  const now = new Date()
  const todayRange = dashboardPeriodRange('day', now)
  const weekRange = dashboardPeriodRange('week', now)
  const monthRange = dashboardPeriodRange('month', now)
  const todayRuns = runs.filter((run) => isWithinRange(run.startedAtIso ?? run.startedAt, todayRange))
  const weekRuns = runs.filter((run) => isWithinRange(run.startedAtIso ?? run.startedAt, weekRange))
  const monthItems = items.filter((item) => isWithinRange(item.observedAt, monthRange))
  const todayAccepted = todayRuns.reduce((total, run) => total + run.acceptedCount, 0)
  const todayRejected = todayRuns.reduce((total, run) => total + run.rejectedCount, 0)
  const weekSuccessful = weekRuns.filter((run) => run.status === 'succeeded').length
  const weekAbnormal = weekRuns.length - weekSuccessful
  const weekSuccessRate = weekRuns.length ? Math.round((weekSuccessful / weekRuns.length) * 100) : null
  const publishedCollectors = collectors.filter((collector) => collector.status === 'published').length
  const monthAccepted = monthItems.filter((item) => item.decision === 'accepted').length
  const monthRejected = monthItems.filter((item) => item.decision === 'rejected').length
  const trendBuckets = useMemo(() => dashboardTrendBuckets(granularity, new Date(), runs), [granularity, runs])
  const trendRange = trendGranularities.find((option) => option.value === granularity)?.range ?? '最近 14 天'
  const trendRuns = trendBuckets.reduce((total, bucket) => total + bucket.runs, 0)
  const successfulRuns = trendBuckets.reduce((total, bucket) => total + bucket.successful, 0)
  const partialRuns = trendBuckets.reduce((total, bucket) => total + bucket.partial, 0)
  const failedRuns = trendBuckets.reduce((total, bucket) => total + bucket.failed, 0)
  const trendAccepted = trendBuckets.reduce((total, bucket) => total + bucket.accepted, 0)
  const trendRejected = trendBuckets.reduce((total, bucket) => total + bucket.rejected, 0)
  const trendSuccessRate = trendRuns ? Math.round((successfulRuns / trendRuns) * 100) : null
  const trendDataPassRate = trendAccepted + trendRejected ? Math.round((trendAccepted / (trendAccepted + trendRejected)) * 100) : null
  const maxRunVolume = Math.max(1, ...trendBuckets.map((bucket) => bucket.volume))
  const isLoading = collectorsQuery.isLoading || runsQuery.isLoading || itemsQuery.isLoading
  const hasError = collectorsQuery.isError || runsQuery.isError || itemsQuery.isError

  return (
    <div className="page-frame dashboard-page overview-dashboard overview-dashboard-board">
      <h1 className="sr-only">概览</h1>

      <header className="overview-board-header">
        <div><strong>采集运营</strong><p>产出、质量与需要介入的异常</p></div>
        <Button asChild><Link to="/collectors/new"><Plus />新建采集器</Link></Button>
      </header>

      {hasError && <div className="dashboard-error" role="alert"><CircleAlert /><span>部分运营数据加载失败，请刷新后重试。</span></div>}

      <section className="overview-kpi-strip" aria-label="核心运营指标">
        <div className="overview-kpi-primary"><span>今日采集</span><strong>{isLoading ? '—' : todayAccepted}</strong><small>{todayRuns.length} 次运行 · {todayRejected} 条拒绝</small></div>
        <div><span>本周运行成功率</span><strong>{isLoading || weekSuccessRate === null ? '—' : `${weekSuccessRate}%`}</strong><small>{weekSuccessful} 次成功 · {weekAbnormal} 次异常</small></div>
        <div><span>本月有效数据</span><strong>{isLoading ? '—' : monthAccepted}</strong><small>{monthItems.length} 个实体 · {monthRejected} 条拒绝</small></div>
        <div><span>规则覆盖</span><strong>{isLoading ? '—' : `${publishedCollectors}/${collectors.length}`}</strong><small>{collectors.length - publishedCollectors > 0 ? `${collectors.length - publishedCollectors} 个尚未发布` : '所有采集器均已发布'}</small></div>
      </section>

      <div className="overview-board-grid">
        <section className="overview-panel overview-trend-panel" aria-labelledby="run-trend-heading">
          <header className="overview-panel-header overview-trend-header">
            <div><h2 id="run-trend-heading">采集产出趋势</h2><p>{trendRange} · 接收与拒绝数据</p></div>
            <div className="overview-trend-actions">
              <div className="overview-period-control" role="group" aria-label="趋势聚合口径">
                {trendGranularities.map((option) => (
                  <button aria-pressed={granularity === option.value} className={granularity === option.value ? 'active' : ''} key={option.value} onClick={() => setGranularity(option.value)} type="button">{option.label}</button>
                ))}
              </div>
              <Link to="/runs">查看运行 <ArrowRight /></Link>
            </div>
          </header>
          {runsQuery.isLoading ? <OverviewSkeleton /> : trendRuns > 0 ? (
            <div className="overview-run-chart" role="group" aria-label={`${trendRange} ${trendRuns} 次运行，${trendAccepted} 条接收，${trendRejected} 条拒绝`}>
              <div className={`overview-chart-bars ${granularity}`}>
                {trendBuckets.map((bucket) => {
                  const height = bucket.volume === 0 ? 0 : Math.max(10, Math.round((bucket.volume / maxRunVolume) * 100))
                  const acceptedShare = bucket.volume ? Math.round((bucket.accepted / bucket.volume) * 100) : 0
                  return (
                    <div className={`overview-chart-point ${bucket.tone}`} key={bucket.key} title={`${bucket.title}：${bucket.runs} 次运行，${bucket.accepted} 接收，${bucket.rejected} 拒绝`}>
                      <span className="overview-chart-bar" style={{ height: `${height}%` }}>
                        <i className="accepted" style={{ height: `${acceptedShare}%` }} />
                        <i className="rejected" style={{ height: `${100 - acceptedShare}%` }} />
                      </span>
                      <small>{bucket.label}</small>
                    </div>
                  )
                })}
              </div>
              <div className="overview-chart-legend"><span className="success"><i />接收 {trendAccepted}</span><span className="danger"><i />拒绝 {trendRejected}</span></div>
            </div>
          ) : <OverviewEmpty title={`${trendRange}尚无运行`} detail="切换聚合口径可查看其他时间范围。" />}
        </section>

        <div className="overview-board-side">
          <section className="overview-panel overview-quality-panel" aria-labelledby="quality-heading">
            <header className="overview-panel-header"><div><h2 id="quality-heading">运行质量</h2><p>{trendRange}</p></div><strong className={trendSuccessRate !== null && trendSuccessRate < 80 ? 'warning-text' : ''}>{trendSuccessRate === null ? '—' : `${trendSuccessRate}%`}</strong></header>
            <div className="overview-quality-body">
              <div className="overview-quality-bar" aria-label={`${successfulRuns} 成功，${partialRuns} 部分成功，${failedRuns} 失败`}>
                {trendRuns > 0 && <><i className="success" style={{ width: `${(successfulRuns / trendRuns) * 100}%` }} /><i className="warning" style={{ width: `${(partialRuns / trendRuns) * 100}%` }} /><i className="danger" style={{ width: `${(failedRuns / trendRuns) * 100}%` }} /></>}
              </div>
              <div className="overview-quality-stats"><span><i className="success" />成功 <strong>{successfulRuns}</strong></span><span><i className="warning" />部分成功 <strong>{partialRuns}</strong></span><span><i className="danger" />失败 <strong>{failedRuns}</strong></span></div>
              <div className="overview-quality-foot"><span>数据通过率</span><strong>{trendDataPassRate === null ? '—' : `${trendDataPassRate}%`}</strong></div>
            </div>
          </section>

          <section className="overview-panel overview-board-attention" aria-labelledby="attention-heading">
            <header className="overview-panel-header"><div><h2 id="attention-heading">需要关注</h2><p>{isLoading ? '正在加载' : attentionItems.length > 0 ? `${attentionItems.length} 项需要人工推进` : '当前没有阻断'}</p></div><Link to="/collectors?view=attention">查看全部 <ArrowRight /></Link></header>
            <div className="overview-board-alerts">
              {isLoading ? <OverviewSkeleton /> : attentionItems.slice(0, 3).map((item) => (
                <Link className="overview-board-alert" to={item.target} key={`${item.collector.id}:${item.label}`}>
                  <span className={`overview-severity ${item.tone}`}><CircleAlert /></span>
                  <span><strong>{item.label}</strong><small>{collectorDisplayName(item.collector.name)} · {item.detail}</small></span>
                  <ArrowRight />
                </Link>
              ))}
              {!isLoading && attentionItems.length === 0 && <OverviewEmpty title="运行正常" detail="当前没有需要人工处理的事项。" />}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function latestEntities(items: HarvestItem[]) {
  const latest = new Map<string, HarvestItem>()
  for (const item of items) {
    const key = `${item.collectorId}:${item.entityKey}`
    const current = latest.get(key)
    if (!current || item.observedAt > current.observedAt) latest.set(key, item)
  }
  return [...latest.values()]
}

function dashboardPeriodRange(period: TrendGranularity, now: Date): DashboardRange {
  if (period === 'day') {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    return { start, end: new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1) }
  }

  if (period === 'week') {
    const mondayOffset = (now.getDay() + 6) % 7
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - mondayOffset)
    return { start, end: new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7) }
  }

  return {
    start: new Date(now.getFullYear(), now.getMonth(), 1),
    end: new Date(now.getFullYear(), now.getMonth() + 1, 1),
  }
}

function parseDashboardDate(value?: string) {
  if (!value) return null
  const parsed = new Date(value.includes('T') ? value : value.replace(' ', 'T'))
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function isWithinRange(value: string, range: DashboardRange) {
  const date = parseDashboardDate(value)
  return date !== null && date >= range.start && date < range.end
}

function dashboardTrendBuckets(granularity: TrendGranularity, now: Date, runs: Run[]): TrendBucket[] {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const currentMonday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - ((today.getDay() + 6) % 7))
  const rangeStart = granularity === 'day'
    ? new Date(today.getFullYear(), today.getMonth(), today.getDate() - 13)
    : granularity === 'week'
      ? new Date(currentMonday.getFullYear(), currentMonday.getMonth(), currentMonday.getDate() - 11 * 7)
      : new Date(today.getFullYear(), today.getMonth() - 11, 1)

  return Array.from({ length: granularity === 'day' ? 14 : 12 }, (_, index) => {
    const start = granularity === 'day'
      ? new Date(rangeStart.getFullYear(), rangeStart.getMonth(), rangeStart.getDate() + index)
      : granularity === 'week'
        ? new Date(rangeStart.getFullYear(), rangeStart.getMonth(), rangeStart.getDate() + index * 7)
        : new Date(rangeStart.getFullYear(), rangeStart.getMonth() + index, 1)
    const end = granularity === 'day'
      ? new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1)
      : granularity === 'week'
        ? new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7)
        : new Date(start.getFullYear(), start.getMonth() + 1, 1)
    const bucketRuns = runs.filter((run) => {
      const runDate = parseDashboardDate(run.startedAtIso ?? run.startedAt)
      return runDate !== null && runDate >= start && runDate < end
    })
    const successful = bucketRuns.filter((run) => run.status === 'succeeded').length
    const partial = bucketRuns.filter((run) => run.status === 'partially_succeeded').length
    const failed = bucketRuns.filter((run) => ['failed', 'cancelled', 'timed_out'].includes(run.status)).length
    const accepted = bucketRuns.reduce((total, run) => total + run.acceptedCount, 0)
    const rejected = bucketRuns.reduce((total, run) => total + run.rejectedCount, 0)
    const volume = accepted + rejected
    const label = granularity === 'month'
      ? `${start.getMonth() + 1}月`
      : `${start.getMonth() + 1}/${start.getDate()}`
    const title = granularity === 'day'
      ? `${start.getMonth() + 1}月${start.getDate()}日`
      : granularity === 'week'
        ? `${start.getMonth() + 1}月${start.getDate()}日所在周`
        : `${start.getFullYear()}年${start.getMonth() + 1}月`

    return {
      key: start.toISOString(),
      label,
      title,
      volume,
      accepted,
      rejected,
      runs: bucketRuns.length,
      successful,
      partial,
      failed,
      tone: failed > 0 ? 'failed' : partial > 0 ? 'partially_succeeded' : successful > 0 ? 'succeeded' : 'empty',
    }
  })
}

function partialRunDetail(run: Run) {
  const missingDetails = run.detailUrlsDiscovered - run.detailPagesFetched
  if (missingDetails > 0) return `详情抓取 ${run.detailPagesFetched}/${run.detailUrlsDiscovered}，${missingDetails} 个未完成`
  if (run.rejectedCount > 0) return `${run.acceptedCount} 条接收 · ${run.rejectedCount} 条拒绝`
  return run.recoveryAction
}

function OverviewSkeleton() {
  return <div className="overview-skeletons">{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-14 w-full" />)}</div>
}

function OverviewEmpty({ title, detail }: { title: string; detail: string }) {
  return <div className="overview-empty"><CheckCircle2 /><span><strong>{title}</strong><small>{detail}</small></span></div>
}
