import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Braces, CheckCircle2, ExternalLink, FileText, Fingerprint, GitCompareArrows, History, Link2, Network, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { HarvestItem } from '@/api/types'
import { StatusBadge } from '@/components/status-badge'
import { collectorSourceLabel } from '@/features/collectors/collector-presentation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function ItemPage() {
  const { itemId = '' } = useParams()
  const query = useQuery({ queryKey: ['item', itemId], queryFn: () => api.item(itemId) })
  if (query.isLoading) return <div className="page-frame"><Skeleton className="h-96 w-full" /></div>
  const item = query.data
  if (!item) return <div className="empty-state"><h1>Item 不存在</h1><Button asChild><Link to="/items">返回数据</Link></Button></div>

  const revisionLabel = item.revision === null ? '未生成 Revision' : `Revision ${item.revision}`
  const businessFacts = [
    ['采购人', item.buyer],
    ['地区', item.region],
    ['预算', item.budget],
  ].filter(([, value]) => hasUsefulBusinessValue(value))

  return (
    <div className="run-workbench item-workbench">
      <div className="run-page-main item-page-main">
        <header className="run-page-header item-page-header">
          <div>
            <div className="title-line"><h1>{item.title}</h1><StatusBadge status={item.decision} /></div>
            <div className="run-header-subtitle">
              <span className="item-source-context">{collectorSourceLabel(item.collectorName, item.sourceHost)}</span>
              <span className="run-header-meta">发布 {item.publishedAt} · {revisionLabel}</span>
            </div>
          </div>
          <Button asChild variant="outline"><a href={item.sourceUrl} target="_blank" rel="noreferrer">打开来源 <ExternalLink /></a></Button>
        </header>

        <Tabs defaultValue="content" className="run-workspace-tabs item-workspace-tabs">
          <div className="run-workspace-nav item-workspace-nav">
            <TabsList variant="line" aria-label="数据详情视图">
              <TabsTrigger value="content"><FileText />数据内容</TabsTrigger>
              <TabsTrigger value="revisions"><GitCompareArrows />版本与观察{item.observationHistory.length > 0 && <span className="tab-count neutral">{item.observationHistory.length}</span>}</TabsTrigger>
              <TabsTrigger value="quality"><ShieldCheck />质量决定</TabsTrigger>
              <TabsTrigger value="lineage"><Fingerprint />来源与谱系</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="content" className="run-tab-panel item-tab-panel">
            <section aria-label="数据内容摘要" className={`item-record-summary ${item.decision === 'accepted' ? 'success' : 'danger'}`}>
              <div className="item-summary-heading">
                <div><h2>{item.decision === 'accepted' ? '规范化数据可用' : '候选数据未通过质量门'}</h2><p>{item.changeType ? changeTypeLabel(item.changeType) : '未进入版本记录'}</p></div>
                <dl className="item-summary-facts">
                  <div><dt>发布时间</dt><dd>{item.publishedAt}</dd></div>
                  <div><dt>最近采集</dt><dd>{item.observedAt}</dd></div>
                  <div><dt>当前版本</dt><dd>{revisionLabel}</dd></div>
                  <div><dt>观察次数</dt><dd>{item.observationHistory.length} 次</dd></div>
                </dl>
              </div>
            </section>

            <section className="run-detail-section item-record-section">
              <header><div><h2>公告内容</h2><p>当前规范化字段与正文</p></div></header>
              {businessFacts.length > 0 && <dl className="item-business-fields">
                {businessFacts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
              </dl>}
              <div className={`item-body-reading${item.content ? '' : ' is-empty'}`}>
                <h3>公告正文</h3>
                <p>{item.content || '未提取正文'}</p>
              </div>
            </section>
          </TabsContent>

          <TabsContent value="revisions" className="run-tab-panel item-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>版本变化</h2><p>{revisionLabel} · {item.changeType ? changeTypeLabel(item.changeType) : '无可发布版本'}</p></div><Badge variant="outline">{item.changeSummary.length} 项变化</Badge></header>
              {item.changeSummary.length > 0 ? <div className="revision-diff item-revision-diff">{item.changeSummary.map((change) => <div key={change.field}><code>{change.field}</code><span className="diff-before">− {change.before}</span><ArrowRight /><span className="diff-after">+ {change.after}</span></div>)}</div> : <div className="revision-empty"><GitCompareArrows /><div><strong>{item.revision === null ? '未生成可发布 Revision' : '这是首个 Revision'}</strong><p>{item.revision === null ? '该候选在质量门被拒绝，因此没有规范化内容差异。' : '没有上一版本可比较；后续内容变化会在这里逐字段展示。'}</p></div></div>}
            </section>

            <section className="run-detail-section">
              <header><div><h2>观察历史</h2><p>同一实体在历次运行中的采集记录</p></div></header>
              {item.observationHistory.length > 0 ? <div className="observation-list item-observation-list">{item.observationHistory.map((observation, index) => <div key={observation.id}><span className="observation-marker">{index === item.observationHistory.length - 1 ? <CheckCircle2 /> : <History />}</span><div><strong>{observation.observedAt}</strong><StatusBadge status={observation.outcome} /><small><Link to={`/runs/${observation.runId}`}>查看对应运行 <ArrowRight /></Link></small></div></div>)}</div> : <div className="card-empty">当前候选没有观察历史。</div>}
            </section>
          </TabsContent>

          <TabsContent value="quality" className="run-tab-panel item-tab-panel">
            <section className="run-detail-section">
              <header><div><h2>质量决定</h2><p>{item.decision === 'accepted' ? '该数据已进入交付集' : '该候选未进入交付集'}</p></div></header>
              {item.rejectionReason && <div className="rejection-banner item-quality-rejection"><strong>拒绝原因</strong><p>{item.rejectionReason}</p></div>}
              <div className="run-proof-grid item-quality-grid">
                <article className={item.decision === 'accepted' ? 'verified' : 'warning'}><ShieldCheck /><span><strong>{item.decision === 'accepted' ? '质量终态通过' : '质量终态拒绝'}</strong><small>{item.decision === 'accepted' ? '可用于下游交付' : '仅保留为候选证据'}</small></span></article>
                <article className={item.title === item.listTitle ? 'verified' : 'warning'}><CheckCircle2 /><span><strong>{item.title === item.listTitle ? '标题一致' : '标题需要复核'}</strong><small>列表标题与详情标题{item.title === item.listTitle ? '一致' : '不同'}</small></span></article>
                <article className="verified"><Network /><span><strong>来源边界通过</strong><small>{item.sourceHost}</small></span></article>
                <article className={item.content ? 'verified' : 'neutral'}><FileText /><span><strong>{item.content ? '正文已提取' : '正文未提取'}</strong><small>{item.content ? '规范化正文可用' : '当前合同允许正文为空'}</small></span></article>
              </div>
            </section>
          </TabsContent>

          <TabsContent value="lineage" className="run-tab-panel item-tab-panel">
            <section className="run-detail-section item-lineage-section">
              <header><div><h2>来源与谱系</h2><p>从采集器、运行到当前数据的可追溯关系</p></div><Fingerprint /></header>
              <div className="item-lineage-links">
                <article><Network /><span><small>采集器</small><Link to={`/collectors/${item.collectorId}`}>{collectorSourceLabel(item.collectorName, item.sourceHost)} <ArrowRight /></Link></span></article>
                <article><Link2 /><span><small>详情来源</small><a href={item.sourceUrl} target="_blank" rel="noreferrer">{item.sourceUrl} <ExternalLink /></a></span></article>
                <article><History /><span><small>最近运行</small><Link to={`/runs/${item.lineage.runId}`}>查看运行记录 <ArrowRight /></Link></span></article>
              </div>
              <details className="run-technical-details item-technical-details">
                <summary><Braces /><span><strong>技术信息</strong><small>用于排障、审计和精确定位</small></span><ArrowRight /></summary>
                <dl>
                  <div><dt>Entity key</dt><dd><code>{item.entityKey}</code></dd></div>
                  <div><dt>Run ID</dt><dd><code>{item.lineage.runId}</code></dd></div>
                  <div><dt>Source Revision</dt><dd><code>{item.lineage.sourceRevision}</code></dd></div>
                  <div><dt>Collection Version</dt><dd><code>{item.lineage.collectionVersion}</code></dd></div>
                  <div><dt>Rule Version</dt><dd><code>{item.lineage.ruleVersion}</code></dd></div>
                  <div><dt>Observation ID</dt><dd><code>{item.lineage.observationId ?? '未生成'}</code></dd></div>
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

function changeTypeLabel(type: NonNullable<HarvestItem['changeType']>) {
  return { new: '新增', updated: '内容已更新', unchanged: '内容未变化' }[type]
}

function hasUsefulBusinessValue(value: string) {
  return !['', '不适用', '未标注', '未披露', '字段缺失', '未知'].includes(value.trim())
}
