import { useQuery } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { ArrowRight, Braces, CheckCircle2, ExternalLink, FileText, Fingerprint, GitCompareArrows, History, Link2, Network, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { HarvestItem } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { collectorSourceLabel } from '@/features/collectors/collector-presentation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function ItemPage() {
  const { t } = useTranslation('items')
  const { itemId = '' } = useParams()
  const query = useQuery({ queryKey: ['item', itemId], queryFn: () => api.item(itemId) })
  if (query.isLoading) return <div className="page-frame"><Skeleton className="h-96 w-full" /></div>
  const item = query.data
  if (!item) return <div className="empty-state"><h1>{t('detail.notFound')}</h1><Button asChild><Link to="/items">{t('detail.backToItems')}</Link></Button></div>

  const revisionLabel = item.revision === null ? t('detail.revisionMissing') : t('detail.revision', { count: item.revision })
  const businessFacts = [
    [t('detail.factBuyer'), item.buyer],
    [t('detail.factRegion'), item.region],
    [t('detail.factBudget'), item.budget],
  ].filter(([, value]) => hasUsefulBusinessValue(value))

  return (
    <div className="run-workbench item-workbench">
      <div className="run-page-main item-page-main">
        <header className="run-page-header item-page-header">
          <div>
            <div className="title-line"><h1>{item.title}</h1><StatusBadge status={item.decision} /></div>
            <div className="run-header-subtitle">
              <span className="item-source-context">{collectorSourceLabel(item.collectorName, item.sourceHost)}</span>
              <span className="run-header-meta">{t('detail.publishedLine', { publishedAt: item.publishedAt, revision: revisionLabel })}</span>
            </div>
          </div>
          <Button asChild variant="outline"><a href={item.sourceUrl} target="_blank" rel="noreferrer">{t('detail.openSource')} <ExternalLink /></a></Button>
        </header>

        <Tabs defaultValue="content" className="run-workspace-tabs item-workspace-tabs">
          <div className="run-workspace-nav item-workspace-nav">
            <TabsList variant="line" aria-label={t('detail.viewsAria')}>
              <TabsTrigger value="content"><FileText />{t('detail.tabContent')}</TabsTrigger>
              <TabsTrigger value="revisions"><GitCompareArrows />{t('detail.tabRevisions')}{item.observationHistory.length > 0 && <span className="tab-count neutral">{item.observationHistory.length}</span>}</TabsTrigger>
              <TabsTrigger value="quality"><ShieldCheck />{t('detail.tabQuality')}</TabsTrigger>
              <TabsTrigger value="lineage"><Fingerprint />{t('detail.tabLineage')}</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="content" className="run-tab-panel item-tab-panel">
            <section aria-label={t('detail.summaryAria')} className={`item-record-summary ${item.decision === 'accepted' ? 'success' : 'danger'}`}>
              <div className="item-summary-heading">
                <div><h2>{item.decision === 'accepted' ? t('detail.normalizedAvailable') : t('detail.rejectedByGate')}</h2><p>{item.changeType ? changeTypeLabel(item.changeType, t) : t('detail.notVersioned')}</p></div>
                <dl className="item-summary-facts">
                  <div><dt>{t('detail.publishedAt')}</dt><dd>{item.publishedAt}</dd></div>
                  <div><dt>{t('detail.observedAt')}</dt><dd>{item.observedAt}</dd></div>
                  <div><dt>{t('detail.currentVersion')}</dt><dd>{revisionLabel}</dd></div>
                  <div><dt>{t('detail.observationCount')}</dt><dd>{t('detail.observationCountValue', { count: item.observationHistory.length })}</dd></div>
                </dl>
              </div>
            </section>

            <section className="run-detail-section item-record-section">
              <header><div><h2>{t('detail.announcementTitle')}</h2><p>{t('detail.announcementSubtitle')}</p></div></header>
              {businessFacts.length > 0 && <dl className="item-business-fields">
                {businessFacts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
              </dl>}
              <div className={`item-body-reading${item.content ? '' : ' is-empty'}`}>
                <h3>{t('detail.announcementBody')}</h3>
                <p>{item.content || t('detail.bodyMissing')}</p>
              </div>
            </section>
          </TabsContent>

          <TabsContent value="revisions" className="run-tab-panel item-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>{t('detail.revisionTitle')}</h2><p>{revisionLabel} · {item.changeType ? changeTypeLabel(item.changeType, t) : t('detail.noPublishableVersion')}</p></div><Badge variant="outline">{t('detail.changeCount', { count: item.changeSummary.length })}</Badge></header>
              {item.changeSummary.length > 0 ? <div className="revision-diff item-revision-diff">{item.changeSummary.map((change) => <div key={change.field}><code>{change.field}</code><span className="diff-before">− {change.before}</span><ArrowRight /><span className="diff-after">+ {change.after}</span></div>)}</div> : <div className="revision-empty"><GitCompareArrows /><div><strong>{item.revision === null ? t('detail.revisionNotGenerated') : t('detail.firstRevision')}</strong><p>{item.revision === null ? t('detail.revisionRejectedDetail') : t('detail.firstRevisionDetail')}</p></div></div>}
            </section>

            <section className="run-detail-section">
              <header><div><h2>{t('detail.observationTitle')}</h2><p>{t('detail.observationSubtitle')}</p></div></header>
              {item.observationHistory.length > 0 ? <div className="observation-list item-observation-list">{item.observationHistory.map((observation, index) => <div key={observation.id}><span className="observation-marker">{index === item.observationHistory.length - 1 ? <CheckCircle2 /> : <History />}</span><div><strong>{observation.observedAt}</strong><StatusBadge status={observation.outcome} /><small><Link to={`/runs/${observation.runId}`}>{t('detail.viewObservationRun')} <ArrowRight /></Link></small></div></div>)}</div> : <div className="card-empty">{t('detail.observationEmpty')}</div>}
            </section>
          </TabsContent>

          <TabsContent value="quality" className="run-tab-panel item-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>{t('detail.qualityTitle')}</h2><p>{item.decision === 'accepted' ? t('detail.qualityAcceptedDetail') : t('detail.qualityRejectedDetail')}</p></div></header>
              {item.rejectionReason && <div className="rejection-banner item-quality-rejection"><strong>{t('detail.rejectionReason')}</strong><p>{item.rejectionReason}</p></div>}
              <div className="run-proof-grid item-quality-grid">
                <article className={item.decision === 'accepted' ? 'verified' : 'warning'}><ShieldCheck /><span><strong>{item.decision === 'accepted' ? t('detail.qualityGatePassed') : t('detail.qualityGateRejected')}</strong><small>{item.decision === 'accepted' ? t('detail.qualityGatePassedDetail') : t('detail.qualityGateRejectedDetail')}</small></span></article>
                <article className={item.title === item.listTitle ? 'verified' : 'warning'}><CheckCircle2 /><span><strong>{item.title === item.listTitle ? t('detail.titleMatch') : t('detail.titleMismatch')}</strong><small>{item.title === item.listTitle ? t('detail.titleConsistent') : t('detail.titleInconsistent')}</small></span></article>
                <article className="verified"><Network /><span><strong>{t('detail.sourceBoundaryPassed')}</strong><small>{item.sourceHost}</small></span></article>
                <article className={item.content ? 'verified' : 'neutral'}><FileText /><span><strong>{item.content ? t('detail.bodyExtracted') : t('detail.bodyNotExtracted')}</strong><small>{item.content ? t('detail.bodyAvailable') : t('detail.bodyOptional')}</small></span></article>
              </div>
            </section>
          </TabsContent>

          <TabsContent value="lineage" className="run-tab-panel item-tab-panel">
            <section className="run-detail-section item-lineage-section">
              <header><div><h2>{t('detail.lineageTitle')}</h2><p>{t('detail.lineageSubtitle')}</p></div><Fingerprint /></header>
              <div className="item-lineage-links">
                <article><Network /><span><small>{t('detail.collectorLabel')}</small><Link to={`/collectors/${item.collectorId}`}>{collectorSourceLabel(item.collectorName, item.sourceHost)} <ArrowRight /></Link></span></article>
                <article><Link2 /><span><small>{t('detail.sourceLabel')}</small><a href={item.sourceUrl} target="_blank" rel="noreferrer">{item.sourceUrl} <ExternalLink /></a></span></article>
                <article><History /><span><small>{t('detail.latestRunLabel')}</small><Link to={`/runs/${item.lineage.runId}`}>{t('detail.viewRunRecord')} <ArrowRight /></Link></span></article>
              </div>
              <details className="run-technical-details item-technical-details">
                <summary><Braces /><span><strong>{t('detail.technicalTitle')}</strong><small>{t('detail.technicalSubtitle')}</small></span><ArrowRight /></summary>
                <dl>
                  <div><dt>Entity key</dt><dd><code>{item.entityKey}</code></dd></div>
                  <div><dt>Run ID</dt><dd><code>{item.lineage.runId}</code></dd></div>
                  <div><dt>Source Revision</dt><dd><code>{item.lineage.sourceRevision}</code></dd></div>
                  <div><dt>Collection Version</dt><dd><code>{item.lineage.collectionVersion}</code></dd></div>
                  <div><dt>Rule Version</dt><dd><code>{item.lineage.ruleVersion}</code></dd></div>
                  <div><dt>Observation ID</dt><dd><code>{item.lineage.observationId ?? t('detail.observationIdMissing')}</code></dd></div>
                  <div><dt>Artifact ID</dt><dd><code>{item.lineage.artifactId}</code></dd></div>
                </dl>
              </details>
            </section>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}

function changeTypeLabel(type: NonNullable<HarvestItem['changeType']>, t: TFunction) {
  return { new: t('detail.change.new'), updated: t('detail.change.updated'), unchanged: t('detail.change.unchanged') }[type]
}

function hasUsefulBusinessValue(value: string) {
  return !['', '不适用', '未标注', '未披露', '字段缺失', '未知'].includes(value.trim())
}
