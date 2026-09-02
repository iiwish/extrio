import { useQuery } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { ArrowRight, CheckCircle2, CircleAlert, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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

function trendGranularityOptions(t: TFunction): { value: TrendGranularity; label: string; range: string }[] {
  return [
    { value: 'day', label: t('granularity.day'), range: t('range.day') },
    { value: 'week', label: t('granularity.week'), range: t('range.week') },
    { value: 'month', label: t('granularity.month'), range: t('range.month') },
  ]
}

function attentionFor(collector: CollectorDetail, latestRun: Run | undefined, t: TFunction): AttentionItem | null {
  if (latestRun && ['failed', 'cancelled', 'timed_out'].includes(latestRun.status)) {
    return { collector, run: latestRun, label: t('attention.fixFailedRun'), detail: latestRun.summary, target: `/runs/${latestRun.id}`, tone: 'danger', rank: 0 }
  }
  if (latestRun?.status === 'partially_succeeded') {
    return { collector, run: latestRun, label: t('attention.partialRun'), detail: partialRunDetail(latestRun, t), target: `/runs/${latestRun.id}`, tone: 'danger', rank: 1 }
  }
  if (collector.status === 'ready_review') {
    return { collector, label: t('attention.reviewRule'), detail: t('attention.reviewRuleDetail'), target: `/collectors/${collector.id}`, tone: 'warning', rank: 2 }
  }
  if (collector.status === 'draft') {
    return { collector, label: t('attention.generateRule'), detail: t('attention.generateRuleDetail'), target: `/collectors/${collector.id}`, tone: 'info', rank: 3 }
  }
  if (collector.status === 'exploring') {
    return { collector, label: t('attention.exploreProgress'), detail: t('attention.exploreProgressDetail'), target: `/collectors/${collector.id}`, tone: 'info', rank: 4 }
  }
  if (collector.status === 'published' && !latestRun) {
    return { collector, label: t('attention.firstRun'), detail: t('attention.firstRunDetail'), target: `/collectors/${collector.id}`, tone: 'info', rank: 5 }
  }
  if (latestRun && latestRun.rejectedCount > 0) {
    return { collector, run: latestRun, label: t('attention.checkRejected'), detail: t('attention.checkRejectedDetail', { count: latestRun.rejectedCount }), target: `/runs/${latestRun.id}`, tone: 'warning', rank: 6 }
  }
  return null
}

export function HomePage() {
  const { t } = useTranslation('home')
  const [granularity, setGranularity] = useState<TrendGranularity>('day')
  const collectorsQuery = useQuery({ queryKey: ['collectors'], queryFn: api.collectors })
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  const itemsQuery = useQuery({ queryKey: ['items'], queryFn: api.items })
  const collectors = useMemo(() => collectorsQuery.data ?? [], [collectorsQuery.data])
  const runs = useMemo(() => runsQuery.data ?? [], [runsQuery.data])
  const items = useMemo(() => latestEntities(itemsQuery.data ?? []), [itemsQuery.data])
  const runById = useMemo(() => new Map(runs.map((run) => [run.id, run])), [runs])
  const attentionItems = useMemo(() => collectors
    .map((collector) => attentionFor(collector, collector.latestRunId ? runById.get(collector.latestRunId) : undefined, t))
    .filter((item): item is AttentionItem => item !== null)
    .sort((left, right) => left.rank - right.rank), [collectors, runById, t])

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
  const granularityOptions = trendGranularityOptions(t)
  const trendBuckets = useMemo(() => dashboardTrendBuckets(granularity, new Date(), runs, t), [granularity, runs, t])
  const trendRange = granularityOptions.find((option) => option.value === granularity)?.range ?? t('range.day')
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
      <h1 className="sr-only">{t('common:nav.overview')}</h1>

      <div className="overview-board-actions">
        <Button asChild><Link to="/collectors/new"><Plus />{t('action.newCollector')}</Link></Button>
      </div>

      {hasError && <div className="dashboard-error" role="alert"><CircleAlert /><span>{t('error.loadFailed')}</span></div>}

      <section className="overview-kpi-strip" aria-label={t('kpi.ariaLabel')}>
        <div className="overview-kpi-primary"><span>{t('kpi.todayCollect')}</span><strong>{isLoading ? '—' : todayAccepted}</strong><small>{t('kpi.todayCollectDetail', { runs: todayRuns.length, rejected: todayRejected })}</small></div>
        <div><span>{t('kpi.weekSuccessRate')}</span><strong>{isLoading || weekSuccessRate === null ? '—' : `${weekSuccessRate}%`}</strong><small>{t('kpi.weekSuccessRateDetail', { success: weekSuccessful, abnormal: weekAbnormal })}</small></div>
        <div><span>{t('kpi.monthValidItems')}</span><strong>{isLoading ? '—' : monthAccepted}</strong><small>{t('kpi.monthValidDetail', { entities: monthItems.length, rejected: monthRejected })}</small></div>
        <div><span>{t('kpi.ruleCoverage')}</span><strong>{isLoading ? '—' : `${publishedCollectors}/${collectors.length}`}</strong><small>{collectors.length - publishedCollectors > 0 ? t('kpi.ruleCoverageUnpublished', { count: collectors.length - publishedCollectors }) : t('kpi.ruleCoverageAll')}</small></div>
      </section>

      <div className="overview-board-grid">
        <section className="overview-panel overview-trend-panel" aria-labelledby="run-trend-heading">
          <header className="overview-panel-header overview-trend-header">
            <div><h2 id="run-trend-heading">{t('trend.title')}</h2><p>{t('trend.subtitle', { range: trendRange })}</p></div>
            <div className="overview-trend-actions">
              <div className="overview-period-control" role="group" aria-label={t('trend.periodAria')}>
                {granularityOptions.map((option) => (
                  <button aria-pressed={granularity === option.value} className={granularity === option.value ? 'active' : ''} key={option.value} onClick={() => setGranularity(option.value)} type="button">{option.label}</button>
                ))}
              </div>
              <Link to="/runs">{t('trend.viewRuns')} <ArrowRight /></Link>
            </div>
          </header>
          {runsQuery.isLoading ? <OverviewSkeleton /> : trendRuns > 0 ? (
            <div className="overview-run-chart" role="group" aria-label={t('trend.chartAria', { range: trendRange, runs: trendRuns, accepted: trendAccepted, rejected: trendRejected })}>
              <div className={`overview-chart-bars ${granularity}`}>
                {trendBuckets.map((bucket) => {
                  const height = bucket.volume === 0 ? 0 : Math.max(10, Math.round((bucket.volume / maxRunVolume) * 100))
                  const acceptedShare = bucket.volume ? Math.round((bucket.accepted / bucket.volume) * 100) : 0
                  return (
                    <div className={`overview-chart-point ${bucket.tone}`} key={bucket.key} title={t('trend.pointTitle', { title: bucket.title, runs: bucket.runs, accepted: bucket.accepted, rejected: bucket.rejected })}>
                      <span className="overview-chart-bar" style={{ height: `${height}%` }}>
                        <i className="accepted" style={{ height: `${acceptedShare}%` }} />
                        <i className="rejected" style={{ height: `${100 - acceptedShare}%` }} />
                      </span>
                      <small>{bucket.label}</small>
                    </div>
                  )
                })}
              </div>
              <div className="overview-chart-legend"><span className="success"><i />{t('trend.legendAccepted', { count: trendAccepted })}</span><span className="danger"><i />{t('trend.legendRejected', { count: trendRejected })}</span></div>
            </div>
          ) : <OverviewEmpty title={t('trend.emptyTitle', { range: trendRange })} detail={t('trend.emptyDetail')} />}
        </section>

        <div className="overview-board-side">
          <section className="overview-panel overview-quality-panel" aria-labelledby="quality-heading">
            <header className="overview-panel-header"><div><h2 id="quality-heading">{t('quality.title')}</h2><p>{trendRange}</p></div><strong className={trendSuccessRate !== null && trendSuccessRate < 80 ? 'warning-text' : ''}>{trendSuccessRate === null ? '—' : `${trendSuccessRate}%`}</strong></header>
            <div className="overview-quality-body">
              <div className="overview-quality-bar" aria-label={t('quality.barAria', { success: successfulRuns, partial: partialRuns, failed: failedRuns })}>
                {trendRuns > 0 && <><i className="success" style={{ width: `${(successfulRuns / trendRuns) * 100}%` }} /><i className="warning" style={{ width: `${(partialRuns / trendRuns) * 100}%` }} /><i className="danger" style={{ width: `${(failedRuns / trendRuns) * 100}%` }} /></>}
              </div>
              <div className="overview-quality-stats"><span><i className="success" />{t('quality.success')} <strong>{successfulRuns}</strong></span><span><i className="warning" />{t('quality.partial')} <strong>{partialRuns}</strong></span><span><i className="danger" />{t('quality.failed')} <strong>{failedRuns}</strong></span></div>
              <div className="overview-quality-foot"><span>{t('quality.dataPassRate')}</span><strong>{trendDataPassRate === null ? '—' : `${trendDataPassRate}%`}</strong></div>
            </div>
          </section>

          <section className="overview-panel overview-board-attention" aria-labelledby="attention-heading">
            <header className="overview-panel-header"><div><h2 id="attention-heading">{t('attention.title')}</h2><p>{isLoading ? t('attention.loading') : attentionItems.length > 0 ? t('attention.count', { count: attentionItems.length }) : t('attention.none')}</p></div><Link to="/collectors?view=attention">{t('attention.viewAll')} <ArrowRight /></Link></header>
            <div className="overview-board-alerts">
              {isLoading ? <OverviewSkeleton /> : attentionItems.slice(0, 3).map((item) => (
                <Link className="overview-board-alert" to={item.target} key={`${item.collector.id}:${item.label}`}>
                  <span className={`overview-severity ${item.tone}`}><CircleAlert /></span>
                  <span><strong>{item.label}</strong><small>{collectorDisplayName(item.collector.name)} · {item.detail}</small></span>
                  <ArrowRight />
                </Link>
              ))}
              {!isLoading && attentionItems.length === 0 && <OverviewEmpty title={t('attention.emptyTitle')} detail={t('attention.emptyDetail')} />}
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

function dashboardTrendBuckets(granularity: TrendGranularity, now: Date, runs: Run[], t: TFunction): TrendBucket[] {
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
      ? t('bucket.monthLabel', { month: start.getMonth() + 1 })
      : t('bucket.dayLabel', { month: start.getMonth() + 1, day: start.getDate() })
    const title = granularity === 'day'
      ? t('bucket.dayTitle', { month: start.getMonth() + 1, day: start.getDate() })
      : granularity === 'week'
        ? t('bucket.weekTitle', { month: start.getMonth() + 1, day: start.getDate() })
        : t('bucket.monthTitle', { year: start.getFullYear(), month: start.getMonth() + 1 })

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

function partialRunDetail(run: Run, t: TFunction) {
  const missingDetails = run.detailUrlsDiscovered - run.detailPagesFetched
  if (missingDetails > 0) return t('attention.partialDetailFetch', { fetched: run.detailPagesFetched, discovered: run.detailUrlsDiscovered, missing: missingDetails })
  if (run.rejectedCount > 0) return t('attention.partialDetailCounts', { accepted: run.acceptedCount, rejected: run.rejectedCount })
  return run.recoveryAction
}

function OverviewSkeleton() {
  return <div className="overview-skeletons">{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-14 w-full" />)}</div>
}

function OverviewEmpty({ title, detail }: { title: string; detail: string }) {
  return <div className="overview-empty"><CheckCircle2 /><span><strong>{title}</strong><small>{detail}</small></span></div>
}
