import { Braces, CheckCircle2, Fingerprint, Link2, Network, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { CandidateField, CollectorDetail, FieldReviewDecision, HarvestItem } from '@/api/types'

interface EvidenceRailProps {
  mode?: 'rail' | 'drawer'
  collector?: CollectorDetail
  field?: CandidateField
  fieldDecision?: FieldReviewDecision
  item?: HarvestItem
}

const decisionKeys: Record<FieldReviewDecision, string> = {
  approved: 'decision.approved',
  risk_accepted: 'decision.risk_accepted',
  excluded: 'decision.excluded',
  pending: 'decision.pending',
}

export function EvidenceRail({ mode = 'rail', collector, field, fieldDecision = 'pending', item }: EvidenceRailProps) {
  const { t } = useTranslation('common')
  if (item) return <ItemEvidence item={item} mode={mode} />

  return (
    <EvidenceContainer mode={mode} label={t('evidence.panelAria')}>
      <EvidenceHeading eyebrow={field ? 'FIELD EVIDENCE' : collector?.candidate ? 'CANDIDATE PROOF' : 'SOURCE PROOF'} title={field ? field.label : collector?.candidate ? t('evidence.candidateProofTitle') : t('evidence.sourceProofTitle')} icon={Fingerprint} />
      {field ? (
        <>
          <section className="evidence-card">
            <EvidenceRow icon={Braces} label="Selector" value={field.selector} mono />
            <EvidenceRow icon={CheckCircle2} label={t('evidence.confidence')} value={`${Math.round(field.confidence * 100)}% · ${field.required ? t('evidence.requiredField') : t('evidence.optionalField')}`} />
            <EvidenceRow icon={ShieldCheck} label={t('evidence.reviewDecision')} value={t(decisionKeys[fieldDecision])} />
          </section>
          {field.warning && <section className="evidence-card evidence-warning"><span className="evidence-label">{t('evidence.qualityWarning')}</span><p>{field.warning}</p></section>}
          <section className="evidence-card"><span className="evidence-label">{t('evidence.extractSample')}</span><p>{field.sample}</p></section>
          <section className="evidence-card code-block"><span className="evidence-label">{t('evidence.domSnippet')}</span><code>{field.evidence}</code></section>
        </>
      ) : (
        <>
          <section className="evidence-card">
            <EvidenceRow icon={Network} label={t('evidence.allowedHosts')} value={collector?.sourceHost ?? t('evidence.awaitingSource')} />
            <EvidenceRow icon={Link2} label={t('evidence.entryUrl')} value={collector?.sourceUrl ?? t('evidence.awaitingSource')} />
            {collector?.candidate && <>
              <EvidenceRow icon={Link2} label={t('evidence.paginationStrategy')} value={collector.candidate.pagination.type === 'page' ? `page · max ${collector.candidate.pagination.maxPages}` : collector.candidate.pagination.type === 'next_link' ? `next_link · max ${collector.candidate.pagination.maxPages}` : 'none'} />
              <EvidenceRow icon={Network} label={collector.candidate.mode === 'single' ? t('evidence.collectionMode') : t('evidence.detailDiscovery')} value={collector.candidate.mode === 'single' ? t('evidence.singleModeValue') : `${collector.candidate.discovery.detailUrlsDiscovered} discovered · ${collector.candidate.discovery.detailPagesValidated} validated`} />
            </>}
          </section>
          {collector?.candidate && <section className="evidence-card"><EvidenceRow icon={CheckCircle2} label={t('evidence.candidateStatus')} value={t('evidence.candidateStatusValue')} /></section>}
          <section className="evidence-card"><span className="evidence-label">{t('evidence.networkBoundary')}</span><p>HTTP(S) policy checked · credentials require HTTPS · redirect re-check · private network denied</p></section>
        </>
      )}
    </EvidenceContainer>
  )
}

function ItemEvidence({ item, mode }: { item: HarvestItem; mode: 'rail' | 'drawer' }) {
  const { t } = useTranslation('common')
  const lineage = [
    ['sourceRevision', item.lineage.sourceRevision],
    ['collectionVersion', item.lineage.collectionVersion],
    ['ruleVersion', item.lineage.ruleVersion],
    ['runId', item.lineage.runId],
    ...(item.lineage.observationId ? [['observationId', item.lineage.observationId] as const] : []),
    ['artifactId', item.lineage.artifactId],
  ] as const

  return (
    <EvidenceContainer mode={mode} label={item.decision === 'rejected' ? t('evidence.rejectedEvidence') : t('evidence.itemLineageEvidence')}>
      <EvidenceHeading eyebrow="LINEAGE" title={item.decision === 'rejected' ? t('evidence.rejectedEvidence') : t('evidence.itemLineage')} icon={Fingerprint} />
      <section className="evidence-card">
        <EvidenceRow icon={Network} label="Collector / Source" value={`${item.collectorName} · ${item.sourceHost}`} />
        <EvidenceRow icon={Link2} label={t('evidence.listTitle')} value={item.listTitle || item.title} />
        <EvidenceRow icon={Link2} label={t('evidence.detailUrl')} value={item.sourceUrl} />
        <EvidenceRow icon={CheckCircle2} label={t('evidence.observedAt')} value={item.observedAt} />
      </section>
      <section className="evidence-card identity-card"><span className="evidence-label">Entity key</span><code>{item.entityKey}</code></section>
      <section className="evidence-card lineage-card" aria-label={t('evidence.lineageChainAria')}>
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
