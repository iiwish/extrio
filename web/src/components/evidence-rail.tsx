import { Braces, CheckCircle2, Fingerprint, Link2, Network, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { CandidateField, CollectorDetail, FieldReviewDecision, HarvestItem } from '@/api/types'

interface EvidenceRailProps {
  mode?: 'rail' | 'drawer'
  collector?: CollectorDetail
  field?: CandidateField
  fieldDecision?: FieldReviewDecision
  item?: HarvestItem
}

const decisionLabel: Record<FieldReviewDecision, string> = {
  approved: '已确认纳入',
  risk_accepted: '已接受风险',
  excluded: '已排除',
  pending: '等待决策',
}

export function EvidenceRail({ mode = 'rail', collector, field, fieldDecision = 'pending', item }: EvidenceRailProps) {
  if (item) return <ItemEvidence item={item} mode={mode} />

  return (
    <EvidenceContainer mode={mode} label="证据面板">
      <EvidenceHeading eyebrow={field ? 'FIELD EVIDENCE' : collector?.candidate ? 'CANDIDATE PROOF' : 'SOURCE PROOF'} title={field ? field.label : collector?.candidate ? '候选规则证据' : 'Source 证据'} icon={Fingerprint} />
      {field ? (
        <>
          <section className="evidence-card">
            <EvidenceRow icon={Braces} label="Selector" value={field.selector} mono />
            <EvidenceRow icon={CheckCircle2} label="置信度" value={`${Math.round(field.confidence * 100)}% · ${field.required ? '必填字段' : '可选字段'}`} />
            <EvidenceRow icon={ShieldCheck} label="审核决定" value={decisionLabel[fieldDecision]} />
          </section>
          {field.warning && <section className="evidence-card evidence-warning"><span className="evidence-label">质量警告</span><p>{field.warning}</p></section>}
          <section className="evidence-card"><span className="evidence-label">提取样本</span><p>{field.sample}</p></section>
          <section className="evidence-card code-block"><span className="evidence-label">DOM 片段</span><code>{field.evidence}</code></section>
        </>
      ) : (
        <>
          <section className="evidence-card">
            <EvidenceRow icon={Network} label="允许主机" value={collector?.sourceHost ?? '等待 Source'} />
            <EvidenceRow icon={Link2} label="采集入口" value={collector?.sourceUrl ?? '等待 Source'} />
            {collector?.candidate && <>
              <EvidenceRow icon={Link2} label="分页策略" value={collector.candidate.pagination.type === 'page' ? `page · max ${collector.candidate.pagination.maxPages}` : collector.candidate.pagination.type === 'next_link' ? `next_link · max ${collector.candidate.pagination.maxPages}` : 'none'} />
              <EvidenceRow icon={Network} label={collector.candidate.mode === 'single' ? '采集模式' : '详情发现'} value={collector.candidate.mode === 'single' ? 'single · 单阶段直接提取' : `${collector.candidate.discovery.detailUrlsDiscovered} discovered · ${collector.candidate.discovery.detailPagesValidated} validated`} />
            </>}
          </section>
          {collector?.candidate && <section className="evidence-card"><EvidenceRow icon={CheckCircle2} label="候选状态" value="已完成校验，等待审核发布" /></section>}
          <section className="evidence-card"><span className="evidence-label">网络边界</span><p>HTTP(S) policy checked · credentials require HTTPS · redirect re-check · private network denied</p></section>
        </>
      )}
    </EvidenceContainer>
  )
}

function ItemEvidence({ item, mode }: { item: HarvestItem; mode: 'rail' | 'drawer' }) {
  const lineage = [
    ['sourceRevision', item.lineage.sourceRevision],
    ['collectionVersion', item.lineage.collectionVersion],
    ['ruleVersion', item.lineage.ruleVersion],
    ['runId', item.lineage.runId],
    ...(item.lineage.observationId ? [['observationId', item.lineage.observationId] as const] : []),
    ['artifactId', item.lineage.artifactId],
  ] as const

  return (
    <EvidenceContainer mode={mode} label={item.decision === 'rejected' ? '拒绝候选证据' : 'Item 谱系证据'}>
      <EvidenceHeading eyebrow="LINEAGE" title={item.decision === 'rejected' ? '拒绝候选证据' : 'Item 谱系'} icon={Fingerprint} />
      <section className="evidence-card">
        <EvidenceRow icon={Network} label="Collector / Source" value={`${item.collectorName} · ${item.sourceHost}`} />
        <EvidenceRow icon={Link2} label="列表标题" value={item.listTitle || item.title} />
        <EvidenceRow icon={Link2} label="详情 URL" value={item.sourceUrl} />
        <EvidenceRow icon={CheckCircle2} label="采集时间" value={item.observedAt} />
      </section>
      <section className="evidence-card identity-card"><span className="evidence-label">Entity key</span><code>{item.entityKey}</code></section>
      <section className="evidence-card lineage-card" aria-label="谱系链">
        {lineage.map(([label, value]) => (
          <div className="lineage-node" key={label}>
            <span className="lineage-dot" aria-hidden="true" />
            <div>
              <span className="evidence-label">{label}</span>
              {label === 'runId' ? <Link className="evidence-link" to={`/runs/${value}`}>{value}</Link> : <code>{value}</code>}
            </div>
          </div>
        ))}
      </section>
    </EvidenceContainer>
  )
}

function EvidenceContainer({ mode, label, children }: { mode: 'rail' | 'drawer'; label: string; children: ReactNode }) {
  if (mode === 'drawer') return <div className="evidence-drawer-panel" role="region" aria-label={label}>{children}</div>
  return <aside className="evidence-rail" aria-label={label}>{children}</aside>
}

function EvidenceHeading({ eyebrow, title, icon: Icon, tone = 'blue' }: { eyebrow: string; title: string; icon: typeof Fingerprint; tone?: 'blue' | 'teal' }) {
  return <div className="evidence-heading"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div><span className={`evidence-heading-icon ${tone}`}><Icon /></span></div>
}

function EvidenceRow({ icon: Icon, label, value, mono = false }: { icon: typeof Braces; label: string; value: string; mono?: boolean }) {
  return <div className="evidence-row"><Icon className="size-4" aria-hidden="true" /><div><span className="evidence-label">{label}</span>{mono ? <code>{value}</code> : <p>{value}</p>}</div></div>
}
