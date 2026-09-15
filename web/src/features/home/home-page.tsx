import { useQuery } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { ArrowRight, CheckCircle2, CircleAlert, Plus, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { CollectorDetail, OverviewBucket, Run } from '@/api/types'
import { useAuth } from '@/features/auth/auth-gate'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { collectorDisplayName } from '@/features/collectors/collector-presentation'
import { collectorAttention } from '@/features/collectors/collector-attention'

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
  const attention = collectorAttention(collector, latestRun)
  if (!attention) return null
  const rank = attention.rank
  if (attention.reason === 'migration' || attention.reason === 'checkPublish') {
    return { collector, label: t(`attention.${attention.reason}`), detail: t(`attention.${attention.reason}Detail`), target: `/collectors/${collector.id}?section=rule`, tone: 'warning', rank: attention.rank }
  }
  if (attention.reason === 'fixFailedRun' && latestRun) {
    return { collector, run: latestRun, label: t('attention.fixFailedRun'), detail: latestRun.summary, target: `/runs/${latestRun.id}`, tone: 'danger', rank }
  }
  if (attention.reason === 'partialRun' && latestRun) {
    return { collector, run: latestRun, label: t('attention.partialRun'), detail: partialRunDetail(latestRun, t), target: `/runs/${latestRun.id}`, tone: 'danger', rank }
  }
  if (attention.reason === 'reviewRule') {
    return { collector, label: t('attention.reviewRule'), detail: t('attention.reviewRuleDetail'), target: `/collectors/${collector.id}`, tone: 'warning', rank }
  }
  if (attention.reason === 'generateRule') {
    return { collector, label: t('attention.generateRule'), detail: t('attention.generateRuleDetail'), target: `/collectors/${collector.id}`, tone: 'info', rank }
  }
  if (attention.reason === 'exploreProgress') {
    return { collector, label: t('attention.exploreProgress'), detail: t('attention.exploreProgressDetail'), target: `/collectors/${collector.id}`, tone: 'info', rank }
  }
  if (attention.reason === 'firstRun' || attention.reason === 'inspectRun') {
    if (collector.latestRunId) return { collector, label: t('attention.inspectRun'), detail: t('common:state.unavailable'), target: `/runs/${collector.latestRunId}`, tone:'info', rank }
    return { collector, label: t('attention.firstRun'), detail: t('attention.firstRunDetail'), target: `/collectors/${collector.id}`, tone: 'info', rank }
  }
  if (attention.reason === 'checkRejected' && latestRun) {
    return { collector, run: latestRun, label: t('attention.checkRejected'), detail: t('attention.checkRejectedDetail', { count: latestRun.rejectedCount }), target: `/runs/${latestRun.id}?section=results&decision=rejected`, tone: 'warning', rank }
  }
  return null
}

export function HomePage() {
  const { t, i18n } = useTranslation('home')
  const { user } = useAuth()
  const [granularity, setGranularity] = useState<TrendGranularity>('day')
  const collectorsQuery = useQuery({ queryKey: ['collectors'], queryFn: () => api.collectors() })
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const overviewQuery = useQuery({ queryKey: ['overview', timezone], queryFn: () => api.overview(timezone), refetchInterval: 60000 })
  const collectors = useMemo(() => collectorsQuery.data ?? [], [collectorsQuery.data])
  const runs = useMemo(() => runsQuery.data ?? [], [runsQuery.data])
  const runById = useMemo(() => new Map(runs.map((run) => [run.id, run])), [runs])
  const attentionItems = useMemo(() => collectors
    .map((collector) => attentionFor(collector, collector.latestRunId ? runById.get(collector.latestRunId) : undefined, t))
    .filter((item): item is AttentionItem => item !== null)
    .sort((left, right) => left.rank - right.rank), [collectors, runById, t])

  const overview = overviewQuery.data
  const weekSuccessRate = overview?.week.completed ? Math.round(overview.week.successful / overview.week.completed * 100) : null
  const granularityOptions = trendGranularityOptions(t)
  const trendBuckets = (overview?.trends[granularity] ?? []).map(bucket => presentBucket(bucket, granularity, t))
  const trendRange = granularityOptions.find((option) => option.value === granularity)?.range ?? t('range.day')
  const trendRuns = trendBuckets.reduce((total, bucket) => total + bucket.runs, 0)
  const successfulRuns = trendBuckets.reduce((total, bucket) => total + bucket.successful, 0)
  const partialRuns = trendBuckets.reduce((total, bucket) => total + bucket.partial, 0)
  const failedRuns = trendBuckets.reduce((total, bucket) => total + bucket.failed, 0)
  const trendAccepted = trendBuckets.reduce((total, bucket) => total + bucket.accepted, 0)
  const trendRejected = trendBuckets.reduce((total, bucket) => total + bucket.rejected, 0)
  const completedRuns = successfulRuns + partialRuns + failedRuns
  const activeRuns = trendRuns - completedRuns
  const trendSuccessRate = completedRuns ? Math.round((successfulRuns / completedRuns) * 100) : null
  const trendDataPassRate = trendAccepted + trendRejected ? Math.round((trendAccepted / (trendAccepted + trendRejected)) * 100) : null
  const maxRunVolume = Math.max(1, ...trendBuckets.map((bucket) => bucket.volume))
  const isLoading = collectorsQuery.isLoading || runsQuery.isLoading
  const attentionError = collectorsQuery.isError || runsQuery.isError
  const hasError = attentionError || overviewQuery.isError
  const unavailable = t(overviewQuery.isLoading ? 'common:state.loading' : 'common:state.unavailable')

  function refresh() {
    void overviewQuery.refetch()
    void collectorsQuery.refetch()
    void runsQuery.refetch()
  }

  return (
    <div className="page-frame dashboard-page overview-dashboard overview-dashboard-board">
      <h1 className="sr-only">{t('common:nav.overview')}</h1>

      <div className="overview-board-actions">
        <span className="overview-snapshot">{overview ? t('snapshot', { timezone: overview.timezone, time: new Date(overview.generatedAt).toLocaleTimeString(i18n.language === 'en' ? 'en-GB' : 'zh-CN', {hour:'2-digit',minute:'2-digit'}) }) : unavailable}</span>
        <Button variant="outline" size="icon-sm" aria-label={t('common:action.refresh')} title={t('common:action.refresh')} disabled={overviewQuery.isFetching || collectorsQuery.isFetching || runsQuery.isFetching} onClick={refresh}><RefreshCw /></Button>
        {(user.role === 'administrator' || user.role === 'engineer') && <Button asChild><Link to="/collectors/new"><Plus />{t('action.newCollector')}</Link></Button>}
      </div>

      {hasError && <div className="dashboard-error" role="alert"><CircleAlert /><span>{t('error.loadFailed')}</span></div>}

      <section className="overview-kpi-strip" aria-label={t('kpi.ariaLabel')}>
        <div className="overview-kpi-primary"><span>{t('kpi.todayCollect')}</span><strong>{overview?.today.accepted ?? '—'}</strong><small>{overview ? t('kpi.todayCollectDetail', { runs: overview.today.runs, rejected: overview.today.rejected }) : unavailable}</small></div>
        <div><span>{t('kpi.weekSuccessRate')}</span><strong>{weekSuccessRate === null ? '—' : `${weekSuccessRate}%`}</strong><small>{overview ? t('kpi.weekSuccessRateDetail', { success: overview.week.successful, abnormal: overview.week.partial + overview.week.failed }) : unavailable}</small></div>
        <div title={t('kpi.monthBasis')}><span>{t('kpi.monthValidItems')}</span><strong>{overview?.monthEntities.accepted ?? '—'}</strong><small>{overview ? t('kpi.monthValidDetail', { entities: overview.monthEntities.total, rejected: overview.monthEntities.rejected }) : unavailable}</small></div>
        <div><span>{t('kpi.ruleCoverage')}</span><strong>{overview ? `${overview.collectors.published}/${overview.collectors.total}` : '—'}</strong><small>{!overview ? unavailable : !overview.collectors.total ? t('kpi.noCollectors') : overview.collectors.total > overview.collectors.published ? t('kpi.ruleCoverageUnpublished', { count: overview.collectors.total - overview.collectors.published }) : t('kpi.ruleCoverageAll')}</small></div>
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
          {overviewQuery.isLoading ? <OverviewSkeleton /> : !overview ? <p className="card-empty">{unavailable}</p> : trendRuns > 0 ? (
            <div className="overview-run-chart" role="group" aria-label={t('trend.chartAria', { range: trendRange, runs: trendRuns, accepted: trendAccepted, rejected: trendRejected })}>
              <div className={`overview-chart-bars ${granularity}`}>
                {trendBuckets.map((bucket) => {
                  const height = bucket.volume === 0 ? 0 : Math.max(10, Math.round((bucket.volume / maxRunVolume) * 100))
                  const acceptedShare = bucket.volume ? Math.round((bucket.accepted / bucket.volume) * 100) : 0
                  return (
                    <div tabIndex={0} className={`overview-chart-point ${bucket.tone}`} key={bucket.key} aria-label={t('trend.pointTitle', { title: bucket.title, runs: bucket.runs, accepted: bucket.accepted, rejected: bucket.rejected })} title={t('trend.pointTitle', { title: bucket.title, runs: bucket.runs, accepted: bucket.accepted, rejected: bucket.rejected })}>
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
                {completedRuns > 0 && <><i className="success" style={{ width: `${(successfulRuns / completedRuns) * 100}%` }} /><i className="warning" style={{ width: `${(partialRuns / completedRuns) * 100}%` }} /><i className="danger" style={{ width: `${(failedRuns / completedRuns) * 100}%` }} /></>}
              </div>
              <div className="overview-quality-stats"><span><i className="success" />{t('quality.success')} <strong>{overview ? successfulRuns : '—'}</strong></span><span><i className="warning" />{t('quality.partial')} <strong>{overview ? partialRuns : '—'}</strong></span><span><i className="danger" />{t('quality.failed')} <strong>{overview ? failedRuns : '—'}</strong></span></div>
              {activeRuns > 0 && <p className="overview-active-runs">{t('quality.active', {count:activeRuns})}</p>}
              <div className="overview-quality-foot"><span>{t('quality.dataPassRate')}</span><strong>{trendDataPassRate === null ? '—' : `${trendDataPassRate}%`}</strong></div>
            </div>
          </section>

          <section className="overview-panel overview-board-attention" aria-labelledby="attention-heading">
            <header className="overview-panel-header"><div><h2 id="attention-heading">{t('attention.title')}</h2><p>{isLoading ? t('attention.loading') : attentionError ? t('common:state.unavailable') : attentionItems.length > 0 ? t('attention.count', { count: attentionItems.length }) : t('attention.none')}</p></div><Link to="/collectors?view=attention">{t('attention.viewAll')} <ArrowRight /></Link></header>
            <div className="overview-board-alerts">
              {isLoading ? <OverviewSkeleton /> : attentionItems.slice(0, 3).map((item) => (
                <Link className="overview-board-alert" to={item.target} key={`${item.collector.id}:${item.label}`}>
                  <span className={`overview-severity ${item.tone}`}><CircleAlert /></span>
                  <span><strong>{item.label}</strong><small>{collectorDisplayName(item.collector.name)} · {item.detail}</small></span>
                  <ArrowRight />
                </Link>
              ))}
              {!isLoading && !attentionError && attentionItems.length === 0 && <OverviewEmpty title={t('attention.emptyTitle')} detail={t('attention.emptyDetail')} />}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function presentBucket(bucket: OverviewBucket, granularity: TrendGranularity, t: TFunction): TrendBucket {
  const [year, month, day] = bucket.labelDate.split('-').map(Number)
  return {
    ...bucket,
    volume: bucket.accepted + bucket.rejected,
    label: t(granularity === 'month' ? 'bucket.monthLabel' : 'bucket.dayLabel', {year, month, day}),
    title: t(`bucket.${granularity}Title`, {year, month, day}),
    tone: bucket.failed > 0 ? 'failed' : bucket.partial > 0 ? 'partially_succeeded' : bucket.successful > 0 ? 'succeeded' : 'empty',
  }
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
